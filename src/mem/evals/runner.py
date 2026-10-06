"""Dataset loading, metric calculation, and release gates for MemX evals."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from ..agents.service import AgentMemory
from ..config.paths import project_root
from ..config.settings import MemoryConfig
from .models import (
    EvalCase,
    EvalCaseResult,
    EvalReport,
    EvalThresholds,
    ExpectedConflict,
    ExpectedFact,
    reciprocal_rank,
)

EvalPath = Union[str, Path]


def default_dataset_path() -> Path:
    return project_root() / "evals" / "datasets" / "core-memory.jsonl"


def default_thresholds_path() -> Path:
    return project_root() / "evals" / "thresholds.json"


def load_eval_cases(path: Optional[EvalPath] = None) -> List[EvalCase]:
    dataset_path = Path(path) if path is not None else default_dataset_path()
    cases: List[EvalCase] = []
    seen = set()
    for line_number, raw_line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
            case = EvalCase.from_mapping(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"invalid eval case at {dataset_path}:{line_number}"
            ) from exc
        if case.case_id in seen:
            raise ValueError(f"duplicate eval case id: {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError(f"eval dataset is empty: {dataset_path}")
    return cases


def load_thresholds(path: Optional[EvalPath] = None) -> EvalThresholds:
    thresholds_path = Path(path) if path is not None else default_thresholds_path()
    payload = json.loads(thresholds_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("eval thresholds must be a JSON object.")
    return EvalThresholds.from_mapping(payload)


def run_eval_suite(
    cases: Sequence[EvalCase],
    thresholds: Optional[EvalThresholds] = None,
    dataset_name: str = "in-memory",
    config: Optional[MemoryConfig] = None,
) -> EvalReport:
    if not cases:
        raise ValueError("eval suite requires at least one case.")
    active_thresholds = thresholds or EvalThresholds()
    active_config = config or MemoryConfig(
        persist_on_write=False,
        persist_on_recall=False,
        reflect_importance_threshold=1,
    )
    results = tuple(_evaluate_case(case, active_config) for case in cases)
    metrics = _aggregate_metrics(results)
    threshold_values = {
        key: float(value) for key, value in asdict(active_thresholds).items()
    }
    failed_gates = tuple(_failed_gates(metrics, threshold_values))
    return EvalReport(
        suite="memx-core-memory",
        dataset=dataset_name,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        passed=not failed_gates,
        metrics=metrics,
        thresholds=threshold_values,
        failed_gates=failed_gates,
        cases=results,
    )


def write_eval_report(report: EvalReport, path: EvalPath) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report_path


def _evaluate_case(case: EvalCase, config: MemoryConfig) -> EvalCaseResult:
    memory = AgentMemory(config)
    scope_id = "eval-" + case.case_id
    session_id = "session-" + case.case_id
    for index, text in enumerate(case.memories):
        memory.observe(
            session_id,
            {"role": "user", "content": text, "ts": 1_700_000_000.0 + index},
            scope_id=scope_id,
        )
    consolidation = memory.reflect(scope_id=scope_id, force=True)
    started = time.perf_counter()
    recalled = memory.recall(
        session_id=session_id,
        query=case.query,
        k=min(case.k, config.max_recall_k),
        scope_id=scope_id,
    )
    latency_ms = (time.perf_counter() - started) * 1_000
    facts = recalled["facts"]
    episodes = recalled["episodes"]
    conflicts = memory.l3.conflict_log(scope_id)
    fact_hits = sum(_fact_present(facts, expected) for expected in case.expected_facts)
    fact_contract_hits = sum(
        _fact_contract_present(facts, expected) for expected in case.expected_facts
    )
    conflict_hits = sum(
        _conflict_present(conflicts, expected)
        for expected in case.expected_conflicts
    )
    episode_hits = sum(
        any(
            term.casefold() in str(item.get("text", "")).casefold() for item in episodes
        )
        for term in case.expected_episode_terms
    )
    fact_mrr = _mean(
        reciprocal_rank(
            facts,
            lambda item, expected=expected: _fact_matches(item, expected),
        )
        for expected in case.expected_facts
    )
    episode_mrr = _mean(
        reciprocal_rank(
            episodes,
            lambda item, term=term: (
                term.casefold() in str(item.get("text", "")).casefold()
            ),
        )
        for term in case.expected_episode_terms
    )
    consolidation_ok = (
        consolidation["failed"] == 0 and consolidation["inbox_remaining"] == 0
    )
    passed = (
        fact_hits == len(case.expected_facts)
        and fact_contract_hits == len(case.expected_facts)
        and conflict_hits == len(case.expected_conflicts)
        and episode_hits == len(case.expected_episode_terms)
        and consolidation_ok
    )
    return EvalCaseResult(
        case_id=case.case_id,
        passed=passed,
        fact_hits=fact_hits,
        fact_total=len(case.expected_facts),
        fact_contract_hits=fact_contract_hits,
        fact_contract_total=len(case.expected_facts),
        conflict_hits=conflict_hits,
        conflict_total=len(case.expected_conflicts),
        episode_hits=episode_hits,
        episode_total=len(case.expected_episode_terms),
        fact_mrr=round(fact_mrr, 6),
        episode_mrr=round(episode_mrr, 6),
        consolidation_ok=consolidation_ok,
        recall_latency_ms=round(latency_ms, 3),
        diagnostics={
            "facts": facts,
            "episodes": episodes,
            "conflicts": conflicts,
            "retrieval": memory.l2.last_retrieval_stats(),
            "consolidation": consolidation,
        },
    )


def _fact_matches(item: Mapping[str, Any], expected: ExpectedFact) -> bool:
    return item.get("fact_key") == expected.key and item.get("value") == expected.value


def _fact_present(items: Sequence[Mapping[str, Any]], expected: ExpectedFact) -> int:
    return int(any(_fact_matches(item, expected) for item in items))


def _fact_contract_present(
    items: Sequence[Mapping[str, Any]], expected: ExpectedFact
) -> int:
    return int(
        any(
            _fact_matches(item, expected)
            and (
                expected.partition is None
                or item.get("partition") == expected.partition
            )
            and (
                expected.mem_type is None
                or item.get("mem_type") == expected.mem_type
            )
            and int(item.get("version", 0)) >= expected.min_version
            and len(item.get("evidence_ids", [])) >= expected.min_evidence_count
            for item in items
        )
    )


def _conflict_present(
    items: Sequence[Mapping[str, Any]], expected: ExpectedConflict
) -> int:
    return int(
        any(
            item.get("fact_key") == expected.key
            and item.get("action") == expected.action
            and (
                expected.conflict_type is None
                or item.get("conflict_type") == expected.conflict_type
            )
            for item in items
        )
    )


def _aggregate_metrics(results: Sequence[EvalCaseResult]) -> Dict[str, float]:
    fact_hits = sum(item.fact_hits for item in results)
    fact_total = sum(item.fact_total for item in results)
    fact_contract_hits = sum(item.fact_contract_hits for item in results)
    fact_contract_total = sum(item.fact_contract_total for item in results)
    conflict_hits = sum(item.conflict_hits for item in results)
    conflict_total = sum(item.conflict_total for item in results)
    episode_hits = sum(item.episode_hits for item in results)
    episode_total = sum(item.episode_total for item in results)
    metrics = {
        "case_pass_rate": _ratio(sum(item.passed for item in results), len(results)),
        "fact_recall": _ratio(fact_hits, fact_total),
        "fact_contract_rate": _ratio(fact_contract_hits, fact_contract_total),
        "conflict_expectation_rate": _ratio(conflict_hits, conflict_total),
        "episode_hit_rate": _ratio(episode_hits, episode_total),
        "fact_mrr": _mean(item.fact_mrr for item in results if item.fact_total),
        "episode_mrr": _mean(
            item.episode_mrr for item in results if item.episode_total
        ),
        "consolidation_success_rate": _ratio(
            sum(item.consolidation_ok for item in results), len(results)
        ),
        "p95_recall_latency_ms": _percentile(
            [item.recall_latency_ms for item in results], 0.95
        ),
    }
    return {key: round(value, 6) for key, value in metrics.items()}


def _failed_gates(
    metrics: Mapping[str, float], thresholds: Mapping[str, float]
) -> Iterable[str]:
    for threshold_name, threshold in thresholds.items():
        if threshold_name.startswith("min_"):
            metric_name = threshold_name[4:]
            if metrics[metric_name] < threshold:
                yield threshold_name
        elif threshold_name.startswith("max_"):
            metric_name = threshold_name[4:]
            if metrics[metric_name] > threshold:
                yield threshold_name


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 1.0


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]
