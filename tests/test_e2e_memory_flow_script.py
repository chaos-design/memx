"""Tests for the standalone E2E memory flow script."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_e2e_memory_flow as e2e  # noqa: E402


def test_dialogue_fixture_covers_required_flow_stages() -> None:
    """Verify the script fixture covers input, duplicate, update, and closure cases.

    输入:
        无；读取 run_e2e_memory_flow.dialogue_fixture。
    输出:
        None；断言 fixture 包含端到端测试所需主题。
    示例:
        示例输入: pytest tests/test_e2e_memory_flow_script.py
        示例输出: fixture 覆盖检查通过。
    """
    turns = e2e.dialogue_fixture()
    captures = {turn.expected_capture for turn in turns}
    topics = {turn.topic for turn in turns}
    editor_messages = [
        turn.content
        for turn in turns
        if "user.preference.editor=VSCode" in turn.content
    ]

    assert len(turns) == 16
    assert {"language", "tooling", "delivery", "workflow", "device"} <= topics
    assert "duplicate_l2_memory" in captures
    assert "temporal_fact_old" in captures
    assert "temporal_fact_new" in captures
    assert "closed_slot" in captures
    assert len(editor_messages) == 2
    assert editor_messages[0] == editor_messages[1]


def test_retrieval_cases_match_expected_fact_values() -> None:
    """Verify retrieval cases are aligned with expected long-term facts.

    输入:
        无；读取 retrieval_cases 和 EXPECTED_FACT_VALUES。
    输出:
        None；断言每个检索用例都对应一个明确 fact 预期。
    示例:
        示例输入: test_retrieval_cases_match_expected_fact_values()
        示例输出: 所有检索 case 均有预期 fact。
    """
    cases = e2e.retrieval_cases()

    assert len(cases) >= 5
    for case in cases:
        assert case.expected_fact_key in e2e.EXPECTED_FACT_VALUES
        assert e2e.EXPECTED_FACT_VALUES[case.expected_fact_key] == case.expected_value
        assert case.query
        assert case.expected_episode_term


def test_clean_memory_dir_rejects_unsafe_paths() -> None:
    """Verify cleanup refuses paths outside the project .memories directory.

    输入:
        无；测试内部传入非法 memory_dir。
    输出:
        None；断言路径穿越与非 .memories 目录被拒绝。
    示例:
        示例输入: e2e.clean_memory_dir("../outside")
        示例输出: ValueError 被捕获。
    """
    with pytest.raises(ValueError):
        e2e.clean_memory_dir("../outside")
    with pytest.raises(ValueError):
        e2e.clean_memory_dir("tmp/e2e")


def test_run_e2e_flow_returns_success_and_cleans_state() -> None:
    """Run the complete script flow through its importable API.

    输入:
        无；测试内部使用独立 .memories/e2e-flow-pytest 目录。
    输出:
        None；断言全部验证点通过且 cleanup 删除生成状态。
    示例:
        示例输入: e2e.run_e2e_flow(FlowOptions(...))
        示例输出: {"passed": True, "validations": [...]}。
    """
    memory_dir = ".memories/e2e-flow-pytest"
    result = e2e.run_e2e_flow(
        e2e.FlowOptions(memory_dir=memory_dir, cleanup=True, verbose=False)
    )

    assert result["passed"] is True
    assert result["validations"]
    assert all(item["passed"] for item in result["validations"])
    assert not (e2e.PROJECT_ROOT / memory_dir).exists()
