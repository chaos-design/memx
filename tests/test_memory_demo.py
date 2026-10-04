"""End-to-end demo tests driven by detailed mock conversations."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

import pytest
from mock_conversations import (
    ALL_MOCK_SCENARIO_GROUPS,
    BOUNDARY_MEMORY_SCENARIOS,
    DEMO_MEMORY_CONFIG_OVERRIDES,
    DEMO_MULTI_TURN_MESSAGES,
    DEMO_RECALL_QUERY,
    DEMO_SCOPE_ID,
    DEMO_SESSION_ID,
    EXCEPTIONAL_OBSERVE_CASES,
    EXCEPTIONAL_RECALL_CASES,
    EXPECTED_FACT_KEYS,
    NORMAL_MEMORY_SCENARIOS,
    PERSONAL_PREFERENCE_DIALOGUE_PATH,
    PERSONAL_PREFERENCE_MEMORY_SCENARIO,
    build_personal_preference_messages,
    load_personal_preference_dialogue_text,
    parse_qa_dialogue,
)

from mem import AgentMemory, MemoryConfig

MEMORY_KEY_PATTERN = re.compile(r"记住\s+([A-Za-z0-9_.-]+)=")
CHINESE_TEXT_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def _observe_demo_conversation(memory: AgentMemory) -> List[Dict[str, Any]]:
    """Replay the detailed demo conversation into AgentMemory.

    输入:
        memory: AgentMemory 实例。
    输出:
        list[dict]: 每一轮 observe 的返回结果。
    示例:
        示例输入: _observe_demo_conversation(AgentMemory(MemoryConfig()))
        示例输出: [{"mem_id": "...", "compress_triggered": False, ...}, ...]
    """
    results = []
    for message in DEMO_MULTI_TURN_MESSAGES:
        results.append(
            memory.observe(
                session_id=DEMO_SESSION_ID,
                msg=message,
                scope_id=DEMO_SCOPE_ID,
            )
        )
    return results


def _preference_fact_keys(messages: List[Dict[str, Any]]) -> List[str]:
    """Extract explicit preference fact keys from observe messages.

    输入:
        messages: role/content/ts 消息列表。
    输出:
        list[str]: 由 "记住 key=value" 提取出的 fact_key。
    示例:
        示例输入: _preference_fact_keys([{"content": "记住 user.preference.food=x"}])
        示例输出: ["user.preference.food"]
    """
    keys = []
    for message in messages:
        keys.extend(MEMORY_KEY_PATTERN.findall(str(message["content"])))
    return keys


def _run_mock_memory_scenario(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Replay a mock scenario and return common verification artifacts.

    输入:
        scenario: mock_conversations 中定义的正常或边界场景。
    输出:
        dict: memory、observe_results、reflection、recall、context。
    示例:
        示例输入: _run_mock_memory_scenario(NORMAL_MEMORY_SCENARIOS[0])
        示例输出: {"memory": AgentMemory(...), "recall": {...}, ...}
    """
    config = MemoryConfig(**scenario["config_overrides"])
    memory = AgentMemory(config)
    observe_results = []
    for message in scenario["messages"]:
        observe_results.append(
            memory.observe(
                session_id=scenario["session_id"],
                msg=message,
                scope_id=scenario["scope_id"],
            )
        )
    reflection = memory.reflect(scope_id=scenario["scope_id"], force=True)
    recall = memory.recall(
        session_id=scenario["session_id"],
        query=scenario["query"],
        k=min(8, config.max_recall_k),
        scope_id=scenario["scope_id"],
    )
    context_query = scenario["query"] or next(iter(scenario["expected_fact_values"]))
    context = memory.get_context(
        session_id=scenario["session_id"],
        query=context_query,
        scope_id=scenario["scope_id"],
    )
    return {
        "memory": memory,
        "observe_results": observe_results,
        "reflection": reflection,
        "recall": recall,
        "context": context,
    }


def test_mock_conversation_catalog_covers_required_data_types() -> None:
    """Verify mock data includes normal, boundary, and exceptional cases.

    输入:
        无；读取 mock_conversations 中的场景清单。
    输出:
        None；断言每类 mock 数据均非空且消息结构完整。
    示例:
        示例输入: pytest tests/test_memory_demo.py
        示例输出: mock 数据目录结构校验通过。
    """
    assert set(ALL_MOCK_SCENARIO_GROUPS) == {
        "normal",
        "boundary",
        "qa_personal_preferences",
        "exceptional_observe",
        "exceptional_recall",
    }
    assert len(NORMAL_MEMORY_SCENARIOS) >= 2
    assert len(BOUNDARY_MEMORY_SCENARIOS) >= 2
    assert len(EXCEPTIONAL_OBSERVE_CASES) >= 3
    assert len(EXCEPTIONAL_RECALL_CASES) >= 2
    for scenario in NORMAL_MEMORY_SCENARIOS + BOUNDARY_MEMORY_SCENARIOS:
        assert scenario["scope_id"]
        assert scenario["session_id"]
        assert scenario["messages"]
        assert scenario["expected_fact_values"]
        for message in scenario["messages"]:
            assert "role" in message
            assert "content" in message
            assert "ts" in message


def test_personal_preference_plain_text_qa_catalog_is_valid() -> None:
    """Verify the generated Chinese preference dialogue is plain-text Q&A.

    输入:
        无；读取 personal_preference_dialogue.txt。
    输出:
        None；断言轮次数、问答结构、中文内容和生活方面覆盖均符合要求。
    示例:
        示例输入: pytest tests/test_memory_demo.py
        示例输出: 纯文本 Q&A fixture 校验通过。
    """
    text = load_personal_preference_dialogue_text()
    turns = parse_qa_dialogue(text)
    messages = build_personal_preference_messages()
    min_turns, max_turns = PERSONAL_PREFERENCE_MEMORY_SCENARIO["turn_range"]
    keys = _preference_fact_keys(messages)
    user_aspects = {
        key.split(".")[2]
        for key in keys
        if key.startswith("user.preference.") and len(key.split(".")) >= 4
    }
    companion_aspects = {
        key.split(".")[2]
        for key in keys
        if key.startswith("companion.preference.") and len(key.split(".")) >= 4
    }

    assert PERSONAL_PREFERENCE_DIALOGUE_PATH.suffix == ".txt"
    assert PERSONAL_PREFERENCE_DIALOGUE_PATH.exists()
    assert min_turns <= len(turns) <= max_turns
    assert len(turns) == 120
    assert len(messages) == len(turns) * 2
    assert len(keys) == len(messages)
    assert "TODO" not in text and "TBD" not in text and "xxx" not in text
    for turn in turns:
        assert turn["question"].startswith("记住 user.preference.")
        assert turn["answer"].startswith("记住 companion.preference.")
        assert CHINESE_TEXT_PATTERN.search(turn["question"])
        assert CHINESE_TEXT_PATTERN.search(turn["answer"])
        assert len(turn["question"]) >= 24
        assert len(turn["answer"]) >= 24
    assert PERSONAL_PREFERENCE_MEMORY_SCENARIO["required_life_aspects"] <= user_aspects
    assert (
        PERSONAL_PREFERENCE_MEMORY_SCENARIO["required_life_aspects"]
        <= companion_aspects
    )


def test_personal_preference_qa_dialogue_persists_real_memory_state() -> None:
    """Verify Q&A preference dialogue writes a real AgentMemory state snapshot.

    输入:
        无；测试内部回放 120 轮中文 Q&A 偏好对话。
    输出:
        None；断言 L2/L3/L4 和 `.memories` 持久化状态真实有效。
    示例:
        示例输入: pytest tests/test_memory_demo.py
        示例输出: `.memories/personal-preference-suite/...` 状态文件存在且可读。
    """
    scenario = PERSONAL_PREFERENCE_MEMORY_SCENARIO
    storage_root = Path(scenario["memory_dir"])
    shutil.rmtree(storage_root, ignore_errors=True)
    memory = AgentMemory(MemoryConfig(**scenario["config_overrides"]))
    observe_results = []
    for message in scenario["messages"]:
        observe_results.append(
            memory.observe(
                session_id=scenario["session_id"],
                msg=message,
                scope_id=scenario["scope_id"],
            )
        )

    reflection = memory.reflect(scope_id=scenario["scope_id"], force=True)
    recall = memory.recall(
        session_id=scenario["session_id"],
        query=scenario["query"],
        k=20,
        scope_id=scenario["scope_id"],
    )
    context = memory.get_context(
        session_id=scenario["session_id"],
        query=scenario["query"],
        scope_id=scenario["scope_id"],
    )
    state = memory.read_stored_state(scenario["scope_id"])
    storage_path = memory.storage_path(scenario["scope_id"])

    assert all(result["storage_path"] == storage_path for result in observe_results)
    assert Path(storage_path).exists()
    assert state is not None
    fact_by_key = {fact["fact_key"]: fact["value"] for fact in state["l3"]["facts"]}
    assert state["scope_id"] == scenario["scope_id"]
    assert state["memory_dir"] == scenario["memory_dir"]
    assert len(state["l2"]) >= len(scenario["messages"])
    assert len(state["l3"]["facts"]) >= len(scenario["messages"])
    assert state["l4"]["nodes"]
    assert reflection["n_facts"] >= len(scenario["messages"])
    assert reflection["n_insights"] >= len(scenario["messages"]) // 2
    assert reflection["graph_audit"]["orphan_edges"] == 0
    for fact_key, expected_value in scenario["expected_fact_values"].items():
        assert fact_by_key[fact_key] == expected_value
    for term in scenario["expected_context_terms"]:
        assert term in context
    assert any(
        fact["fact_key"] in scenario["expected_fact_values"]
        for fact in recall["facts"]
    )
    assert recall["episodes"]


def test_agent_memory_demo_multi_turn_conversation_flow() -> None:
    """Verify the full memory flow with a reusable multi-turn mock.

    输入:
        无；测试内部构造 AgentMemory 并回放 mock 对话。
    输出:
        None；断言 L0/L1 压缩、L2 召回、L3 事实和 L4 图谱均可用。
    示例:
        示例输入: pytest tests/test_memory_demo.py
        示例输出: 该 demo 测试通过。
    """
    config = MemoryConfig(**DEMO_MEMORY_CONFIG_OVERRIDES)
    memory = AgentMemory(config)

    observe_results = _observe_demo_conversation(memory)
    compress_count = sum(
        1 for result in observe_results if result["compress_triggered"]
    )
    promoted_ids = {
        mem_id for result in observe_results for mem_id in result["promoted"]
    }

    assert compress_count >= 3
    assert len(promoted_ids) >= 3

    reflection = memory.reflect(scope_id=DEMO_SCOPE_ID, force=True)
    assert reflection["n_facts"] >= len(EXPECTED_FACT_KEYS)
    assert reflection["n_insights"] >= 2
    assert reflection["graph_audit"]["orphan_edges"] == 0

    recall = memory.recall(
        session_id=DEMO_SESSION_ID,
        query=DEMO_RECALL_QUERY,
        k=8,
        entities=["project", "mock"],
        scope_id=DEMO_SCOPE_ID,
    )
    fact_by_key = {fact["fact_key"]: fact["value"] for fact in recall["facts"]}

    assert EXPECTED_FACT_KEYS <= set(fact_by_key)
    assert fact_by_key["user.lang_pref"] == "zh"
    assert fact_by_key["project.memory_style"] == "server-side robust aggregation"
    assert fact_by_key["task.decision"] == "use_mock_file"
    assert len(recall["episodes"]) >= 2
    assert recall["reinforced"]
    assert recall["subgraph"]["nodes"]

    context = memory.get_context(
        session_id=DEMO_SESSION_ID,
        query=DEMO_RECALL_QUERY,
        scope_id=DEMO_SCOPE_ID,
    )
    assert "Summary:" in context
    assert "Facts:" in context
    assert "Episodes:" in context
    assert "server-side robust aggregation" in context

    search_result = memory.search(
        session_id=DEMO_SESSION_ID,
        query="mock file decision",
        scope_id=DEMO_SCOPE_ID,
        k=5,
    )
    assert any(fact["fact_key"] == "task.decision" for fact in search_result["facts"])

    snapshot = memory.architecture_snapshot(DEMO_SCOPE_ID)
    assert snapshot["scope_id"] == DEMO_SCOPE_ID
    assert snapshot["l2"]["active"] >= 3
    assert snapshot["l3"]["facts"] >= len(EXPECTED_FACT_KEYS)
    assert snapshot["l4"]["nodes"] >= 2


@pytest.mark.parametrize(
    "scenario",
    NORMAL_MEMORY_SCENARIOS,
    ids=lambda scenario: scenario["name"],
)
def test_agent_memory_normal_mock_scenarios(scenario: Dict[str, Any]) -> None:
    """Verify normal mock scenarios can complete the full memory flow.

    输入:
        scenario: 正常多轮 mock 对话场景。
    输出:
        None；断言事实、上下文和架构快照符合预期。
    示例:
        示例输入: test_agent_memory_normal_mock_scenarios(NORMAL_MEMORY_SCENARIOS[0])
        示例输出: 正常场景完整链路通过。
    """
    result = _run_mock_memory_scenario(scenario)
    fact_by_key = {
        fact["fact_key"]: fact["value"] for fact in result["recall"]["facts"]
    }

    assert result["reflection"]["n_facts"] >= len(scenario["expected_fact_values"])
    assert set(scenario["expected_fact_values"]) <= set(fact_by_key)
    for fact_key, expected_value in scenario["expected_fact_values"].items():
        assert fact_by_key[fact_key] == expected_value
    for term in scenario["expected_context_terms"]:
        assert term in result["context"]

    snapshot = result["memory"].architecture_snapshot(scenario["scope_id"])
    assert snapshot["l2"]["active"] >= len(scenario["expected_fact_values"])
    assert snapshot["l3"]["facts"] >= len(scenario["expected_fact_values"])


@pytest.mark.parametrize(
    "scenario",
    BOUNDARY_MEMORY_SCENARIOS,
    ids=lambda scenario: scenario["name"],
)
def test_agent_memory_boundary_mock_scenarios(scenario: Dict[str, Any]) -> None:
    """Verify boundary mock scenarios remain deterministic and searchable.

    输入:
        scenario: 边界 mock 对话场景。
    输出:
        None；断言单条记忆、空 query 和重复写入均被稳定处理。
    示例:
        示例输入:
            test_agent_memory_boundary_mock_scenarios(BOUNDARY_MEMORY_SCENARIOS[0])
        示例输出: 边界场景测试通过。
    """
    result = _run_mock_memory_scenario(scenario)
    fact_by_key = {
        fact["fact_key"]: fact["value"] for fact in result["recall"]["facts"]
    }
    promoted_ids = {
        mem_id
        for observe_result in result["observe_results"]
        for mem_id in observe_result["promoted"]
    }

    assert promoted_ids
    assert set(scenario["expected_fact_values"]) <= set(fact_by_key)
    for fact_key, expected_value in scenario["expected_fact_values"].items():
        assert fact_by_key[fact_key] == expected_value
    for term in scenario["expected_context_terms"]:
        assert term in result["context"]


@pytest.mark.parametrize(
    "case",
    EXCEPTIONAL_OBSERVE_CASES,
    ids=lambda case: case["name"],
)
def test_agent_memory_exceptional_observe_cases(case: Dict[str, Any]) -> None:
    """Verify exceptional observe mock data maps to explicit exceptions.

    输入:
        case: 异常 observe mock 数据。
    输出:
        None；断言异常类型和核心错误信息符合预期。
    示例:
        示例输入:
            test_agent_memory_exceptional_observe_cases(EXCEPTIONAL_OBSERVE_CASES[0])
        示例输出: 异常输入被明确拒绝。
    """
    memory = AgentMemory(MemoryConfig())
    with pytest.raises(case["expected_exception"]) as exc_info:
        memory.observe(
            session_id=case["session_id"],
            msg=case["message"],
            scope_id=case["scope_id"],
        )
    assert case["expected_message"] in str(exc_info.value)


@pytest.mark.parametrize(
    "case",
    EXCEPTIONAL_RECALL_CASES,
    ids=lambda case: case["name"],
)
def test_agent_memory_exceptional_recall_cases(case: Dict[str, Any]) -> None:
    """Verify exceptional recall mock data covers k boundary failures.

    输入:
        case: 异常 recall mock 数据。
    输出:
        None；断言非法 k 会触发 ValueError。
    示例:
        示例输入:
            test_agent_memory_exceptional_recall_cases(EXCEPTIONAL_RECALL_CASES[0])
        示例输出: 非法 k 被明确拒绝。
    """
    memory = AgentMemory(MemoryConfig())
    with pytest.raises(case["expected_exception"]) as exc_info:
        memory.recall(
            session_id=case["session_id"],
            query=case["query"],
            k=case["k"],
        )
    assert case["expected_message"] in str(exc_info.value)
