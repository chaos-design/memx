"""Tests for the deterministic MemX quality evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mem.evals import (
    EvalCase,
    EvalThresholds,
    ExpectedConflict,
    ExpectedFact,
    load_eval_cases,
    load_thresholds,
    run_eval_suite,
)
from mem.evals.__main__ import main
from mem.evals.runner import write_eval_report


def test_core_eval_dataset_passes_quality_gates() -> None:
    cases = load_eval_cases()
    thresholds = load_thresholds()

    report = run_eval_suite(cases, thresholds, dataset_name="core-memory.jsonl")

    assert len(cases) == 14
    assert report.passed is True
    assert report.failed_gates == ()
    assert report.metrics["case_pass_rate"] == 1.0
    assert report.metrics["fact_recall"] == 1.0
    assert report.metrics["fact_contract_rate"] == 1.0
    assert report.metrics["conflict_expectation_rate"] == 1.0
    assert report.metrics["episode_hit_rate"] == 1.0
    assert all(item.consolidation_ok for item in report.cases)
    temporal = next(item for item in report.cases if item.case_id == "temporal-update")
    assert temporal.conflict_hits == temporal.conflict_total == 1
    assert temporal.fact_contract_hits == temporal.fact_contract_total == 1


def test_eval_threshold_regression_is_reported() -> None:
    cases = load_eval_cases()[:1]
    thresholds = EvalThresholds(max_p95_recall_latency_ms=-1.0)

    report = run_eval_suite(cases, thresholds)

    assert report.passed is False
    assert report.failed_gates == ("max_p95_recall_latency_ms",)


def test_eval_fact_contract_regression_is_reported() -> None:
    case = EvalCase(
        case_id="wrong-partition",
        description="A fact value can match while its governance contract is wrong.",
        memories=("记住 project.owner=Alice，项目负责人是 Alice。",),
        query="project owner Alice",
        expected_facts=(
            ExpectedFact(
                key="project.owner",
                value="Alice",
                partition="preference",
                mem_type="preference",
            ),
        ),
        expected_episode_terms=("Alice",),
    )

    report = run_eval_suite([case])

    assert report.passed is False
    assert report.metrics["fact_recall"] == 1.0
    assert report.metrics["fact_contract_rate"] == 0.0
    assert "min_fact_contract_rate" in report.failed_gates
    assert report.cases[0].fact_hits == 1
    assert report.cases[0].fact_contract_hits == 0


def test_eval_missing_conflict_regression_is_reported() -> None:
    case = EvalCase(
        case_id="missing-conflict",
        description="A required conflict audit event must not silently disappear.",
        memories=("记住 device.os=Android，当前设备是 Android。",),
        query="current device os Android",
        expected_facts=(
            ExpectedFact(
                key="device.os",
                value="Android",
                partition="semantic",
                mem_type="semantic",
            ),
        ),
        expected_conflicts=(
            ExpectedConflict(
                key="device.os",
                action="archive",
                conflict_type="temporal",
            ),
        ),
        expected_episode_terms=("Android",),
    )

    report = run_eval_suite([case])

    assert report.passed is False
    assert report.metrics["conflict_expectation_rate"] == 0.0
    assert "min_conflict_expectation_rate" in report.failed_gates
    assert report.cases[0].conflict_hits == 0
    assert report.cases[0].conflict_total == 1


def test_eval_loader_rejects_duplicate_and_invalid_cases(tmp_path: Path) -> None:
    duplicate_path = tmp_path / "duplicate.jsonl"
    row = {
        "case_id": "same",
        "memories": ["remember x=y"],
        "query": "x",
        "expected_facts": [{"key": "x", "value": "y"}],
    }
    duplicate_path.write_text(
        json.dumps(row) + "\n" + json.dumps(row) + "\n",
        encoding="utf-8",
    )
    invalid_path = tmp_path / "invalid.jsonl"
    invalid_path.write_text("{}\n", encoding="utf-8")
    invalid_contract_path = tmp_path / "invalid-contract.jsonl"
    invalid_contract = {
        "case_id": "invalid-contract",
        "memories": ["remember x=y"],
        "query": "x",
        "expected_facts": [
            {"key": "x", "value": "y", "min_evidence_count": 0}
        ],
    }
    invalid_contract_path.write_text(
        json.dumps(invalid_contract) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate eval case id"):
        load_eval_cases(duplicate_path)
    with pytest.raises(ValueError, match="invalid eval case"):
        load_eval_cases(invalid_path)
    with pytest.raises(ValueError, match="invalid eval case"):
        load_eval_cases(invalid_contract_path)


def test_eval_cli_writes_report_and_honors_gate_exit_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "report.json"
    exit_code = main(["--output", str(output_path), "--fail-on-regression"])
    payload = json.loads(capsys.readouterr().out)
    written = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["passed"] is True
    assert written["suite"] == "memx-core-memory"
    assert (
        write_eval_report(run_eval_suite(load_eval_cases()), output_path) == output_path
    )
