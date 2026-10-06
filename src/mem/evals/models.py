"""Typed contracts for repeatable MemX evaluation suites."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ExpectedFact:
    """One fact contract expected after consolidation and recall."""

    key: str
    value: Any
    partition: Optional[str] = None
    mem_type: Optional[str] = None
    min_version: int = 1
    min_evidence_count: int = 1

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExpectedFact":
        key = str(payload.get("key", "")).strip()
        if not key or "value" not in payload:
            raise ValueError("expected facts require non-empty key and value fields.")
        min_version = int(payload.get("min_version", 1))
        min_evidence_count = int(payload.get("min_evidence_count", 1))
        if min_version <= 0 or min_evidence_count <= 0:
            raise ValueError(
                "expected fact version and evidence count must be positive."
            )
        partition = _optional_text(payload.get("partition"))
        mem_type = _optional_text(payload.get("mem_type"))
        return cls(
            key=key,
            value=payload["value"],
            partition=partition,
            mem_type=mem_type,
            min_version=min_version,
            min_evidence_count=min_evidence_count,
        )


@dataclass(frozen=True)
class ExpectedConflict:
    """One conflict audit record expected after consolidation."""

    key: str
    action: str
    conflict_type: Optional[str] = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExpectedConflict":
        key = str(payload.get("key", "")).strip()
        action = str(payload.get("action", "")).strip()
        if not key or not action:
            raise ValueError("expected conflicts require non-empty key and action.")
        return cls(
            key=key,
            action=action,
            conflict_type=_optional_text(payload.get("conflict_type")),
        )


@dataclass(frozen=True)
class EvalCase:
    """A self-contained memory write, consolidation, and recall scenario."""

    case_id: str
    description: str
    memories: Tuple[str, ...]
    query: str
    expected_facts: Tuple[ExpectedFact, ...] = field(default_factory=tuple)
    expected_conflicts: Tuple[ExpectedConflict, ...] = field(default_factory=tuple)
    expected_episode_terms: Tuple[str, ...] = field(default_factory=tuple)
    k: int = 5

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvalCase":
        case_id = str(payload.get("case_id", "")).strip()
        query = str(payload.get("query", "")).strip()
        memories = tuple(str(item).strip() for item in payload.get("memories", []))
        if (
            not case_id
            or not query
            or not memories
            or any(not item for item in memories)
        ):
            raise ValueError(
                "eval cases require case_id, query, and non-empty memories."
            )
        facts = tuple(
            ExpectedFact.from_mapping(item)
            for item in payload.get("expected_facts", [])
        )
        conflicts = tuple(
            ExpectedConflict.from_mapping(item)
            for item in payload.get("expected_conflicts", [])
        )
        terms = tuple(
            str(item).strip() for item in payload.get("expected_episode_terms", [])
        )
        if not facts and not conflicts and not terms:
            raise ValueError(
                "eval cases require at least one fact, conflict, "
                "or episode expectation."
            )
        k = int(payload.get("k", 5))
        if k <= 0:
            raise ValueError("eval case k must be positive.")
        return cls(
            case_id=case_id,
            description=str(payload.get("description", "")).strip(),
            memories=memories,
            query=query,
            expected_facts=facts,
            expected_conflicts=conflicts,
            expected_episode_terms=terms,
            k=k,
        )


@dataclass(frozen=True)
class EvalThresholds:
    """Release gates applied to aggregate evaluation metrics."""

    min_case_pass_rate: float = 1.0
    min_fact_recall: float = 1.0
    min_fact_contract_rate: float = 1.0
    min_conflict_expectation_rate: float = 1.0
    min_episode_hit_rate: float = 1.0
    min_fact_mrr: float = 0.8
    min_episode_mrr: float = 0.8
    min_consolidation_success_rate: float = 1.0
    max_p95_recall_latency_ms: float = 80.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvalThresholds":
        return cls(**{key: float(value) for key, value in payload.items()})


@dataclass(frozen=True)
class EvalCaseResult:
    """Measured result for one evaluation case."""

    case_id: str
    passed: bool
    fact_hits: int
    fact_total: int
    fact_contract_hits: int
    fact_contract_total: int
    conflict_hits: int
    conflict_total: int
    episode_hits: int
    episode_total: int
    fact_mrr: float
    episode_mrr: float
    consolidation_ok: bool
    recall_latency_ms: float
    diagnostics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvalReport:
    """Complete suite result with aggregate metrics and gate failures."""

    suite: str
    dataset: str
    generated_at: str
    passed: bool
    metrics: Dict[str, float]
    thresholds: Dict[str, float]
    failed_gates: Tuple[str, ...]
    cases: Tuple[EvalCaseResult, ...]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["cases"] = [item.to_dict() for item in self.cases]
        payload["failed_gates"] = list(self.failed_gates)
        return payload


def reciprocal_rank(values: Sequence[Mapping[str, Any]], predicate: Any) -> float:
    """Return the reciprocal rank of the first item matching a predicate."""
    for index, value in enumerate(values, start=1):
        if predicate(value):
            return 1.0 / index
    return 0.0


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
