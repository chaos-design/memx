#!/usr/bin/env python3
# coverage: ignore file
"""End-to-end MemX flow script.

Run from the memx project root:
    python3 scripts/run_e2e_memory_flow.py
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mem import AgentMemory, MemoryConfig  # noqa: E402
from mem.config.paths import resolve_project_path, validate_memory_dir  # noqa: E402
from mem.embedding.vector import token_count  # noqa: E402

LOGGER = logging.getLogger("memx_e2e")

DEFAULT_MEMORY_DIR = ".memories/e2e-flow-script"
SCOPE_ID = "scope-e2e-memory-flow"
SESSION_ID = "session-e2e-memory-flow"
EXPECTED_FACT_VALUES = {
    "user.lang_pref": "zh",
    "user.preference.editor": "VSCode",
    "project.delivery.deadline": "2026-07-15",
    "workflow.release_checklist": "run_linter_pytest_functional_validation",
    "device.os": "Android",
}


@dataclass(frozen=True)
class DialogueTurn:
    """One mock dialogue message for the E2E flow."""

    role: str
    content: str
    ts: float
    topic: str
    expected_capture: str


@dataclass(frozen=True)
class RetrievalCase:
    """One retrieval validation case."""

    name: str
    query: str
    expected_fact_key: str
    expected_value: str
    expected_episode_term: str
    entities: Optional[List[str]] = None


@dataclass(frozen=True)
class FlowOptions:
    """Runtime options for the E2E flow."""

    memory_dir: str = DEFAULT_MEMORY_DIR
    cleanup: bool = False
    verbose: bool = True


@dataclass
class ValidationResult:
    """Validation output for one checkpoint."""

    name: str
    expected: str
    actual: str
    passed: bool


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    输入:
        argv: 可选命令行参数；None 表示读取 sys.argv。
    输出:
        argparse.Namespace: 解析后的参数对象。
    示例:
        示例输入: parse_args(["--memory-dir", ".memories/demo"])
        示例输出: Namespace(memory_dir=".memories/demo", ...)
    """
    parser = argparse.ArgumentParser(
        description="Run an end-to-end MemX memory flow verification.",
    )
    parser.add_argument(
        "--memory-dir",
        default=DEFAULT_MEMORY_DIR,
        help="Project-relative .memories directory used by this run.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove the generated memory directory after a successful run.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print validation results and the final report path.",
    )
    return parser.parse_args(argv)


def configure_logging(verbose: bool) -> None:
    """Configure console logging.

    输入:
        verbose: True 输出完整流程日志；False 仅输出校验摘要。
    输出:
        None。
    示例:
        示例输入: configure_logging(True)
        示例输出: logging 已设置为 INFO。
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not verbose:
        LOGGER.setLevel(logging.WARNING)


def dialogue_fixture() -> List[DialogueTurn]:
    """Build multi-topic dialogue input for the E2E flow.

    输入:
        无。
    输出:
        list[DialogueTurn]: 覆盖语言、工具、项目、流程、设备和报告偏好的对话。
    示例:
        示例输入: dialogue_fixture()
        示例输出: [DialogueTurn(role="user", topic="scope", ...), ...]
    """
    base_ts = 1_901_000_000.0
    rows = [
        (
            "user",
            (
                "我们正在设计 MemX 端到端验证，目标覆盖输入、分块、"
                "embedding、巩固和检索。"
            ),
            "scope",
            "raw_dialogue",
        ),
        (
            "assistant",
            "我会记录每一层的状态，并输出可人工核验的验证点。",
            "scope",
            "raw_dialogue",
        ),
        (
            "user",
            "记住 user.lang_pref=zh，语言偏好是中文。",
            "language",
            "fact:user.lang_pref",
        ),
        (
            "assistant",
            "已记录语言偏好，后续检索应能召回 user.lang_pref。",
            "language",
            "raw_dialogue",
        ),
        (
            "user",
            "记住 user.preference.editor=VSCode，默认编辑器偏好是 VSCode。",
            "tooling",
            "fact:user.preference.editor",
        ),
        (
            "user",
            "记住 user.preference.editor=VSCode，默认编辑器偏好是 VSCode。",
            "tooling",
            "duplicate_l2_memory",
        ),
        (
            "user",
            (
                "记住 project.delivery.deadline=2026-07-15，交付前必须完成 "
                "linter、pytest 和功能验证。"
            ),
            "delivery",
            "fact:project.delivery.deadline",
        ),
        (
            "assistant",
            "交付日期和验证要求会进入长期记忆候选。",
            "delivery",
            "raw_dialogue",
        ),
        (
            "user",
            (
                "记住 workflow.release_checklist="
                "run_linter_pytest_functional_validation，发布前流程是先跑"
                "静态检查、单元测试和功能验证。"
            ),
            "workflow",
            "fact:workflow.release_checklist",
        ),
        (
            "user",
            "记住 device.os=iOS，当前调试设备系统是 iOS。",
            "device",
            "temporal_fact_old",
        ),
        (
            "assistant",
            "我会先按 iOS 设备上下文理解调试信息。",
            "device",
            "raw_dialogue",
        ),
        (
            "user",
            (
                "记住 device.os=Android，设备系统已更新为 Android，"
                "需要长期记忆保留最新版本。"
            ),
            "device",
            "temporal_fact_new",
        ),
        (
            "user",
            "偏好：输出测试报告时要先给结论，再列验证点和失败原因。",
            "reporting",
            "preference_text",
        ),
        (
            "assistant",
            "报告会包含结论、验证点、失败原因和检索效果。",
            "reporting",
            "raw_dialogue",
        ),
        (
            "user",
            "完成：端到端脚本需要展示 L0、L1、L2、L3、L4 每层结果。",
            "closure",
            "closed_slot",
        ),
        (
            "user",
            "完成：发布验证点已确认，任务闭合。",
            "closure",
            "closed_slot",
        ),
    ]
    return [
        DialogueTurn(
            role=role,
            content=content,
            ts=base_ts + index,
            topic=topic,
            expected_capture=expected_capture,
        )
        for index, (role, content, topic, expected_capture) in enumerate(rows, start=1)
    ]


def retrieval_cases() -> List[RetrievalCase]:
    """Build retrieval cases with expected facts and episode terms.

    输入:
        无。
    输出:
        list[RetrievalCase]: 不同主题的语义检索验证用例。
    示例:
        示例输入: retrieval_cases()
        示例输出: [RetrievalCase(name="language_preference", ...), ...]
    """
    return [
        RetrievalCase(
            name="language_preference",
            query="中文 语言偏好 user.lang_pref",
            expected_fact_key="user.lang_pref",
            expected_value="zh",
            expected_episode_term="语言偏好",
            entities=["user", "语言偏好"],
        ),
        RetrievalCase(
            name="editor_preference",
            query="VSCode editor preference",
            expected_fact_key="user.preference.editor",
            expected_value="VSCode",
            expected_episode_term="VSCode",
            entities=["editor", "VSCode"],
        ),
        RetrievalCase(
            name="delivery_deadline",
            query="deadline 2026-07-15 delivery",
            expected_fact_key="project.delivery.deadline",
            expected_value="2026-07-15",
            expected_episode_term="2026-07-15",
            entities=["project", "delivery"],
        ),
        RetrievalCase(
            name="release_workflow",
            query="release checklist linter pytest functional validation",
            expected_fact_key="workflow.release_checklist",
            expected_value="run_linter_pytest_functional_validation",
            expected_episode_term="静态检查",
            entities=["workflow", "release_checklist"],
        ),
        RetrievalCase(
            name="device_latest_state",
            query="device os Android",
            expected_fact_key="device.os",
            expected_value="Android",
            expected_episode_term="Android",
            entities=["device", "Android"],
        ),
    ]


def clean_memory_dir(memory_dir: str) -> None:
    """Remove the previous E2E memory directory.

    输入:
        memory_dir: 项目根目录下 .memories 内的相对目录。
    输出:
        None。
    示例:
        示例输入: clean_memory_dir(".memories/e2e-flow-script")
        示例输出: 旧测试状态目录被清理。
    """
    relative = validate_memory_dir(memory_dir)
    path = resolve_project_path(relative, PROJECT_ROOT)
    shutil.rmtree(path, ignore_errors=True)


def build_memory(memory_dir: str) -> AgentMemory:
    """Create an AgentMemory instance configured for deterministic E2E testing.

    输入:
        memory_dir: 项目相对记忆目录。
    输出:
        AgentMemory: 使用内存 Adapter 和本地 deterministic embedding 的实例。
    示例:
        示例输入: build_memory(".memories/e2e-flow-script")
        示例输出: AgentMemory 实例。
    """
    config = MemoryConfig(
        flush_turns=4,
        raw_window_turns=6,
        working_memory_tokens=160,
        reflect_importance_threshold=1,
        retrieval_candidate_multiplier=3,
        max_recall_k=20,
        memory_dir=memory_dir,
    )
    return AgentMemory(config)


def log_section(title: str) -> None:
    """Print a section title.

    输入:
        title: 章节标题。
    输出:
        None。
    示例:
        示例输入: log_section("输入对话环节")
        示例输出: 控制台打印章节分隔符。
    """
    LOGGER.info("")
    LOGGER.info("=" * 88)
    LOGGER.info("%s", title)
    LOGGER.info("=" * 88)


def preview(text: str, limit: int = 96) -> str:
    """Return a compact one-line text preview.

    输入:
        text: 原始文本。
        limit: 最大展示长度。
    输出:
        str: 单行预览文本。
    示例:
        示例输入: preview("hello", 3)
        示例输出: "hel..."
    """
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def add_validation(
    results: List[ValidationResult],
    name: str,
    expected: str,
    actual: Any,
    passed: bool,
) -> None:
    """Append and log one validation result.

    输入:
        results: 校验结果列表。
        name: 校验点名称。
        expected: 预期结果说明。
        actual: 实际结果。
        passed: 是否通过。
    输出:
        None。
    示例:
        示例输入: add_validation([], "count", ">=1", 2, True)
        示例输出: ValidationResult 被追加。
    """
    result = ValidationResult(
        name=name,
        expected=expected,
        actual=str(actual),
        passed=passed,
    )
    results.append(result)
    marker = "PASS" if passed else "FAIL"
    LOGGER.warning("[%s] %s | expected=%s | actual=%s", marker, name, expected, actual)


def replay_dialogue(
    memory: AgentMemory,
    turns: List[DialogueTurn],
) -> List[Dict[str, Any]]:
    """Replay mock dialogue through AgentMemory.observe.

    输入:
        memory: AgentMemory 实例。
        turns: 多轮对话 fixture。
    输出:
        list[dict]: 每轮 observe 的返回结果。
    示例:
        示例输入: replay_dialogue(memory, dialogue_fixture())
        示例输出: [{"promoted": [...], "compress_triggered": False}, ...]
    """
    log_section("1. 输入对话环节：多主题对话写入 L0/L1/L2")
    observe_results = []
    for index, turn in enumerate(turns, start=1):
        result = memory.observe(
            session_id=SESSION_ID,
            msg={"role": turn.role, "content": turn.content, "ts": turn.ts},
            scope_id=SCOPE_ID,
        )
        observe_results.append(result)
        LOGGER.info(
            "#%02d role=%s topic=%s capture=%s promoted=%s compress=%s text=%s",
            index,
            turn.role,
            turn.topic,
            turn.expected_capture,
            result["promoted"],
            result["compress_triggered"],
            preview(turn.content),
        )
    return observe_results


def inspect_processing(memory: AgentMemory) -> Dict[str, Any]:
    """Inspect L1 chunking, L2 embeddings, and association storage.

    输入:
        memory: 已完成 observe 的 AgentMemory 实例。
    输出:
        dict: L1/L2 处理阶段诊断信息。
    示例:
        示例输入: inspect_processing(memory)
        示例输出: {"l1_token_used": 42, "l2_records": [...]}。
    """
    log_section("2. 记忆处理环节：语义分块、embedding、结构化候选和关联存储")
    active = memory.l1.get_active_context(SESSION_ID, SCOPE_ID)
    l2_records = memory.l2.all_records(SCOPE_ID)
    diagnostics = {
        "l1_summary": active.rolling_summary,
        "l1_open_slots": list(active.open_slots),
        "l1_entities": list(active.mentioned_entities),
        "l1_token_used": active.token_used,
        "l2_records": [record.to_dict() for record in l2_records],
    }

    LOGGER.info("L1 token_used=%s", active.token_used)
    LOGGER.info("L1 rolling_summary=%s", preview(active.rolling_summary, 180))
    LOGGER.info("L1 mentioned_entities=%s", active.mentioned_entities[:12])
    LOGGER.info("L1 open_slots=%s", len(active.open_slots))
    for slot in active.open_slots[:6]:
        LOGGER.info(
            "  slot id=%s status=%s text=%s",
            slot.get("slot_id"),
            slot.get("status"),
            preview(str(slot.get("text", "")), 90),
        )

    for record in l2_records:
        non_zero_dims = sum(1 for value in record.embedding if value)
        LOGGER.info(
            "L2 mem=%s type=%s importance=%s status=%s tokens=%s "
            "embedding_dim=%s non_zero_dims=%s sources=%s text=%s",
            record.mem_id,
            record.mem_type.value,
            record.importance,
            record.status.value,
            token_count(record.text),
            len(record.embedding),
            non_zero_dims,
            record.source_ids,
            preview(record.text, 110),
        )
    LOGGER.info("Inbox pending=%s", memory.inbox.pending_count(SCOPE_ID))
    return diagnostics


def consolidate_memory(memory: AgentMemory) -> Dict[str, Any]:
    """Run long-term consolidation and inspect L3/L4 outputs.

    输入:
        memory: 已写入 L2/inbox 的 AgentMemory 实例。
    输出:
        dict: reflect 结果、事实、图谱和持久化状态。
    示例:
        示例输入: consolidate_memory(memory)
        示例输出: {"reflection": {"n_facts": 5}, "facts": [...]}。
    """
    log_section("3. 记忆巩固环节：重要性、去重、知识融合和长期记忆更新")
    reflection = memory.reflect(scope_id=SCOPE_ID, force=True)
    facts = [fact.to_dict() for fact in memory.l3.all_facts(SCOPE_ID)]
    nodes = [node.to_dict() for node in memory.l4.all_nodes(SCOPE_ID)]
    edges = [edge.to_dict() for edge in memory.l4.all_edges(SCOPE_ID)]
    device_versions = [
        fact.to_dict() for fact in memory.l3.versions("device.os", SCOPE_ID)
    ]
    state = memory.read_stored_state(SCOPE_ID)

    LOGGER.info("Reflect result=%s", json.dumps(reflection, ensure_ascii=False))
    LOGGER.info("L3 facts=%s", len(facts))
    for fact in facts:
        LOGGER.info(
            "  fact key=%s value=%s confidence=%.2f version=%s "
            "partition=%s evidence=%s",
            fact["fact_key"],
            fact["value"],
            fact["confidence"],
            fact["version"],
            fact["partition"],
            fact["evidence_ids"],
        )
    LOGGER.info("device.os versions=%s", device_versions)
    LOGGER.info("L4 nodes=%s edges=%s", len(nodes), len(edges))
    for node in nodes[:8]:
        LOGGER.info(
            "  node type=%s label=%s salience=%.2f evidence=%s",
            node["type"],
            preview(node["label"], 80),
            node["salience"],
            node["evidence_ids"],
        )

    return {
        "reflection": reflection,
        "facts": facts,
        "nodes": nodes,
        "edges": edges,
        "device_versions": device_versions,
        "stored_state": state,
    }


def find_fact(recall_result: Dict[str, Any], fact_key: str) -> Optional[Dict[str, Any]]:
    """Find one fact in a recall result.

    输入:
        recall_result: memory.recall 返回值。
        fact_key: 目标事实键。
    输出:
        dict | None: 命中的 fact 字典。
    示例:
        示例输入: find_fact({"facts": [{"fact_key": "k"}]}, "k")
        示例输出: {"fact_key": "k"}。
    """
    for fact in recall_result["facts"]:
        if fact["fact_key"] == fact_key:
            return fact
    return None


def run_retrieval_cases(memory: AgentMemory) -> List[Dict[str, Any]]:
    """Run semantic retrieval cases and print recall quality evidence.

    输入:
        memory: 已完成 reflect 的 AgentMemory 实例。
    输出:
        list[dict]: 每个 query 的召回结果和预期命中。
    示例:
        示例输入: run_retrieval_cases(memory)
        示例输出: [{"case": "language_preference", "matched_fact": {...}}, ...]
    """
    log_section("4. 知识检索环节：多 query 语义检索和相关记忆召回")
    outputs = []
    for case in retrieval_cases():
        recall_result = memory.recall(
            session_id=SESSION_ID,
            query=case.query,
            k=8,
            entities=case.entities,
            scope_id=SCOPE_ID,
        )
        matched_fact = find_fact(recall_result, case.expected_fact_key)
        episode_texts = [episode["text"] for episode in recall_result["episodes"]]
        episode_hit = any(case.expected_episode_term in text for text in episode_texts)
        LOGGER.info("")
        LOGGER.info("case=%s query=%s", case.name, case.query)
        LOGGER.info(
            "  expected_fact=%s:%s matched=%s",
            case.expected_fact_key,
            case.expected_value,
            matched_fact,
        )
        LOGGER.info("  episode_hit=%s reinforced=%s", episode_hit, recall_result)
        outputs.append(
            {
                "case": asdict(case),
                "recall": recall_result,
                "matched_fact": matched_fact,
                "episode_hit": episode_hit,
            }
        )
    return outputs


def validate_flow(
    memory: AgentMemory,
    observe_results: List[Dict[str, Any]],
    processing: Dict[str, Any],
    consolidation: Dict[str, Any],
    retrieval_outputs: List[Dict[str, Any]],
) -> List[ValidationResult]:
    """Validate all E2E checkpoints.

    输入:
        memory: AgentMemory 实例。
        observe_results: observe 阶段结果。
        processing: 处理阶段诊断。
        consolidation: reflect 阶段输出。
        retrieval_outputs: 检索阶段输出。
    输出:
        list[ValidationResult]: 全部验证点结果。
    示例:
        示例输入: validate_flow(memory, observe_results, processing, c, r)
        示例输出: [ValidationResult(name="input_messages", passed=True, ...)]
    """
    log_section("5. 输出展示环节：预期结果与验证点")
    validations: List[ValidationResult] = []
    promoted_ids = [
        mem_id
        for result in observe_results
        for mem_id in result["promoted"]
        if mem_id
    ]
    unique_promoted_ids = sorted(set(promoted_ids))
    duplicate_promotions = len(promoted_ids) - len(unique_promoted_ids)
    compress_count = sum(
        1 for result in observe_results if result["compress_triggered"]
    )
    l2_records = memory.l2.all_records(SCOPE_ID)
    explicit_records = [
        record
        for record in l2_records
        if "记住" in record.text or "remember" in record.text.lower()
    ]
    fact_by_key = {fact["fact_key"]: fact for fact in consolidation["facts"]}
    storage_path = memory.storage_path(SCOPE_ID)
    storage_exists = (PROJECT_ROOT / storage_path).exists()
    device_versions = consolidation["device_versions"]
    graph_audit = memory.graph_audit(SCOPE_ID, repair=False)

    add_validation(
        validations,
        "输入对话全部写入",
        f"{len(dialogue_fixture())} messages observed",
        len(observe_results),
        len(observe_results) == len(dialogue_fixture()),
    )
    add_validation(
        validations,
        "L0 达到多次压缩触发",
        "compress_triggered >= 3",
        compress_count,
        compress_count >= 3,
    )
    add_validation(
        validations,
        "显式记忆被提升到 L2",
        "unique promoted memories >= expected facts",
        len(unique_promoted_ids),
        len(unique_promoted_ids) >= len(EXPECTED_FACT_VALUES),
    )
    add_validation(
        validations,
        "重复记忆完成 L2 去重",
        "duplicate promoted mem_id count >= 1",
        duplicate_promotions,
        duplicate_promotions >= 1,
    )
    add_validation(
        validations,
        "L1 语义分块和摘要存在",
        "summary, slots, entities are non-empty",
        {
            "summary": bool(processing["l1_summary"]),
            "slots": len(processing["l1_open_slots"]),
            "entities": len(processing["l1_entities"]),
        },
        bool(processing["l1_summary"])
        and bool(processing["l1_open_slots"])
        and bool(processing["l1_entities"]),
    )
    add_validation(
        validations,
        "L2 embedding 生成完整",
        f"all embeddings dim={memory.config.embedding_dimensions}",
        [len(record.embedding) for record in l2_records],
        bool(l2_records)
        and all(
            len(record.embedding) == memory.config.embedding_dimensions
            for record in l2_records
        ),
    )
    add_validation(
        validations,
        "重要性评分覆盖显式记忆",
        "all explicit memories importance >= 6",
        [record.importance for record in explicit_records],
        bool(explicit_records)
        and all(record.importance >= 6 for record in explicit_records),
    )
    add_validation(
        validations,
        "L3 长期事实覆盖预期 key",
        str(sorted(EXPECTED_FACT_VALUES)),
        sorted(fact_by_key),
        set(EXPECTED_FACT_VALUES) <= set(fact_by_key),
    )
    for fact_key, expected_value in EXPECTED_FACT_VALUES.items():
        actual = fact_by_key.get(fact_key, {}).get("value")
        add_validation(
            validations,
            f"L3 fact value: {fact_key}",
            expected_value,
            actual,
            actual == expected_value,
        )
    add_validation(
        validations,
        "时序事实完成长期记忆更新",
        "device.os has 2 versions and latest=Android",
        device_versions,
        len(device_versions) == 2
        and device_versions[-1]["value"] == "Android"
        and device_versions[0]["valid_until"] is not None,
    )
    add_validation(
        validations,
        "L4 关联图谱写入并通过审计",
        "nodes > 0, edges > 0, orphan_edges == 0",
        {
            "nodes": len(consolidation["nodes"]),
            "edges": len(consolidation["edges"]),
            "audit": graph_audit,
        },
        bool(consolidation["nodes"])
        and bool(consolidation["edges"])
        and graph_audit["orphan_edges"] == 0,
    )
    add_validation(
        validations,
        "持久化快照可读取",
        "memory-state.json exists and stored_state is not None",
        {"path": storage_path, "exists": storage_exists},
        storage_exists and consolidation["stored_state"] is not None,
    )

    for output in retrieval_outputs:
        case = RetrievalCase(**output["case"])
        matched_fact = output["matched_fact"]
        fact_value = matched_fact["value"] if matched_fact else None
        add_validation(
            validations,
            f"Recall fact hit: {case.name}",
            f"{case.expected_fact_key}={case.expected_value}",
            fact_value,
            matched_fact is not None and fact_value == case.expected_value,
        )
        add_validation(
            validations,
            f"Recall episode hit: {case.name}",
            f"episode contains {case.expected_episode_term}",
            output["episode_hit"],
            bool(output["episode_hit"]),
        )
    return validations


def write_report(
    options: FlowOptions,
    observe_results: List[Dict[str, Any]],
    processing: Dict[str, Any],
    consolidation: Dict[str, Any],
    retrieval_outputs: List[Dict[str, Any]],
    validations: List[ValidationResult],
) -> Path:
    """Write a JSON report for manual inspection.

    输入:
        options: 运行配置。
        observe_results: 输入阶段结果。
        processing: 处理阶段结果。
        consolidation: 巩固阶段结果。
        retrieval_outputs: 检索阶段结果。
        validations: 校验结果。
    输出:
        Path: 写入的报告文件绝对路径。
    示例:
        示例输入: write_report(options, [], {}, {}, [], [])
        示例输出: Path(".../.memories/e2e-flow-script/e2e-flow-report.json")
    """
    relative = validate_memory_dir(options.memory_dir)
    report_dir = resolve_project_path(relative, PROJECT_ROOT)
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "scope_id": SCOPE_ID,
        "session_id": SESSION_ID,
        "memory_dir": options.memory_dir,
        "expected_fact_values": EXPECTED_FACT_VALUES,
        "observe_results": observe_results,
        "processing": processing,
        "consolidation": consolidation,
        "retrieval_outputs": retrieval_outputs,
        "validations": [asdict(item) for item in validations],
        "passed": all(item.passed for item in validations),
    }
    report_path = report_dir / "e2e-flow-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report_path


def run_e2e_flow(options: FlowOptions) -> Dict[str, Any]:
    """Run the full observe, process, consolidate, retrieve, and validate flow.

    输入:
        options: FlowOptions 运行配置。
    输出:
        dict: report_path、passed、validations 等运行摘要。
    示例:
        示例输入: run_e2e_flow(FlowOptions(memory_dir=".memories/e2e-flow-script"))
        示例输出: {"passed": True, "report_path": "..."}。
    """
    validate_memory_dir(options.memory_dir)
    clean_memory_dir(options.memory_dir)
    memory = build_memory(options.memory_dir)
    turns = dialogue_fixture()
    observe_results = replay_dialogue(memory, turns)
    processing = inspect_processing(memory)
    consolidation = consolidate_memory(memory)
    retrieval_outputs = run_retrieval_cases(memory)
    validations = validate_flow(
        memory,
        observe_results,
        processing,
        consolidation,
        retrieval_outputs,
    )
    report_path = write_report(
        options,
        observe_results,
        processing,
        consolidation,
        retrieval_outputs,
        validations,
    )
    passed = all(result.passed for result in validations)
    LOGGER.warning("")
    LOGGER.warning("Final status: %s", "PASS" if passed else "FAIL")
    LOGGER.warning("Report: %s", report_path)
    if options.cleanup and passed:
        clean_memory_dir(options.memory_dir)
        LOGGER.warning("Cleaned generated memory directory: %s", options.memory_dir)
    return {
        "passed": passed,
        "report_path": str(report_path),
        "validations": [asdict(result) for result in validations],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the E2E script from command line.

    输入:
        argv: 可选命令行参数。
    输出:
        int: 0 表示全部验证通过，1 表示至少一个验证点失败。
    示例:
        示例输入: main(["--quiet"])
        示例输出: 0
    """
    args = parse_args(argv)
    options = FlowOptions(
        memory_dir=args.memory_dir,
        cleanup=args.cleanup,
        verbose=not args.quiet,
    )
    configure_logging(options.verbose)
    result = run_e2e_flow(options)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
