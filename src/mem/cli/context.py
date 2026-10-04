"""Runtime context helpers for MemX CLI commands."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..agents.service import AgentMemory
from ..config import MemoryConfig, load_memory_config
from ..memory.models import EpisodicMemory
from ..persistence.hydration import restore_scope_state
from ..retrieval.global_search import records_from_snapshot_state


@dataclass
class CliContext:
    """Runtime objects shared by memory command handlers.

    输入:
        memory: AgentMemory service instance.
        session_id: 默认会话 ID。
        scope_id: 默认作用域 ID。
        loaded_state: 从持久化快照恢复出的摘要。
    输出:
        CliContext: 可供 handler 调用的运行上下文。
    示例:
        示例输入: CliContext(memory, "s1", "scope")
        示例输出: context.scope_id == "scope"
    """

    memory: AgentMemory
    session_id: str
    scope_id: str
    loaded_state: Dict[str, Any] = field(default_factory=dict)


def build_context(args: Any) -> CliContext:
    """Create AgentMemory and hydrate stored state when available.

    输入:
        args: argparse parsed namespace。
    输出:
        CliContext: 包含 AgentMemory 与恢复摘要的上下文。
    示例:
        示例输入: build_context(parse_args(["snapshot"]))
        示例输出: CliContext(memory=AgentMemory(...), ...)
    """
    config = load_cli_config(args)
    memory = AgentMemory(config)
    loaded_state: Dict[str, Any] = {}
    if config.backend_mode == "memory" and not args.no_load_state:
        stored_state = memory.read_stored_state(args.scope_id)
        if stored_state is not None:
            loaded_state = restore_scope_state(memory, stored_state)
    return CliContext(
        memory=memory,
        session_id=args.session_id,
        scope_id=args.scope_id,
        loaded_state=loaded_state,
    )


def load_cli_config(args: Any) -> MemoryConfig:
    """Load MemoryConfig from hms.json plus CLI overrides.

    输入:
        args: argparse parsed namespace。
    输出:
        MemoryConfig: 已校验配置对象。
    示例:
        示例输入: load_cli_config(args)
        示例输出: MemoryConfig(...)
    """
    overrides: Dict[str, Any] = {}
    if args.memory_dir:
        overrides["memory_dir"] = args.memory_dir
    if args.backend_mode:
        overrides["backend_mode"] = args.backend_mode
    if args.persist_on_write is not None:
        overrides["persist_on_write"] = args.persist_on_write
    return load_memory_config(path=args.config_path, overrides=overrides)


def finalize_payload(context: CliContext, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Flush dirty memory scope and return an updated payload.

    输入:
        context: CLI runtime context。
        payload: 命令原始结果。
    输出:
        dict: 如发生 flush 则包含 storage_path。
    示例:
        示例输入: finalize_payload(context, {"ok": True})
        示例输出: {"ok": True, "storage_path": "..."}
    """
    finalized = dict(payload)
    if context.memory.persistence.is_dirty(context.scope_id):
        finalized["storage_path"] = context.memory.flush(context.scope_id)
    return finalized


def summarize_snapshot(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Summarize a full architecture snapshot for CLI output.

    输入:
        snapshot: AgentMemory.architecture_snapshot 返回值。
    输出:
        dict: L0-L4、inbox、persistence 与 backend 摘要。
    示例:
        示例输入: summarize_snapshot({"scope_id": "s", "l2": {"active": 1}, ...})
        示例输出: {"scope_id": "s", "l2_active": 1, ...}
    """
    return {
        "scope_id": snapshot["scope_id"],
        "l0_sessions": len(snapshot["l0_sessions"]),
        "l1_sessions": len(snapshot["l1_sessions"]),
        "l2_active": snapshot["l2"]["active"],
        "l2_archived": snapshot["l2"]["archived"],
        "l2_deleted": snapshot["l2"]["deleted"],
        "l2_occupancy": snapshot["l2"]["occupancy"],
        "l3_facts": snapshot["l3"]["facts"],
        "l3_conflicts": snapshot["l3"]["conflicts"],
        "l4_nodes": snapshot["l4"]["nodes"],
        "l4_edges": snapshot["l4"]["edges"],
        "inbox": snapshot["inbox"],
        "persistence": snapshot["persistence"],
        "backend": snapshot["backend"]["profile"],
        "last_retrieval": snapshot["l2"]["last_retrieval"],
    }


def summarize_state(
    memory: AgentMemory,
    scope_id: str,
    state: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Summarize persisted scope state.

    输入:
        memory: AgentMemory service instance。
        scope_id: 作用域 ID。
        state: read_stored_state 返回值。
    输出:
        dict: persisted state counters。
    示例:
        示例输入: summarize_state(memory, "scope", None)
        示例输出: {"exists": False, "storage_path": "..."}
    """
    storage_path = memory.storage_path(scope_id)
    if state is None:
        return {"exists": False, "storage_path": storage_path}
    l3 = state.get("l3", {})
    l4 = state.get("l4", {})
    return {
        "exists": True,
        "storage_path": storage_path,
        "scope_id": state.get("scope_id", scope_id),
        "memory_dir": state.get("memory_dir"),
        "l0_sessions": len(state.get("l0", {})),
        "l1_sessions": len(state.get("l1", [])),
        "l2_records": len(state.get("l2", [])),
        "l3_facts": len(l3.get("facts", [])) if isinstance(l3, Mapping) else 0,
        "l3_conflicts": len(l3.get("conflicts", [])) if isinstance(l3, Mapping) else 0,
        "l4_nodes": len(l4.get("nodes", [])) if isinstance(l4, Mapping) else 0,
        "l4_edges": len(l4.get("edges", [])) if isinstance(l4, Mapping) else 0,
        "inbox_items": len(state.get("inbox", [])),
    }


def current_scope_records(context: CliContext) -> List[EpisodicMemory]:
    """Return restored L2 records for the current CLI scope.

    输入:
        context: CLI runtime context。
    输出:
        list[EpisodicMemory]: 当前 scope 的 L2 记录。
    示例:
        示例输入: current_scope_records(context)
        示例输出: [EpisodicMemory(...)]
    """
    return context.memory.l2.all_records(context.scope_id)


def snapshot_records(context: CliContext, all_scopes: bool) -> List[EpisodicMemory]:
    """Return L2 records from current scope or all stored snapshots.

    输入:
        context: CLI runtime context。
        all_scopes: 是否扫描 memory_dir 下所有 scope 快照。
    输出:
        list[EpisodicMemory]: 可用于全局检索的 L2 记录。
    示例:
        示例输入: snapshot_records(context, all_scopes=False)
        示例输出: current_scope_records(context)
    """
    if not all_scopes:
        return current_scope_records(context)
    records: List[EpisodicMemory] = []
    for state in iter_scope_states(context):
        records.extend(records_from_snapshot_state(state, context.memory.config))
    return records


def iter_scope_states(context: CliContext) -> List[Dict[str, Any]]:
    """Read every stored scope state under the configured memory directory.

    输入:
        context: CLI runtime context。
    输出:
        list[dict]: memory-state.json 对象列表。
    示例:
        示例输入: iter_scope_states(context)
        示例输出: [{"scope_id": "scope", ...}]
    """
    base_dir = Path(context.memory.storage.base_dir)
    states: List[Dict[str, Any]] = []
    for state_path in sorted(base_dir.glob("scopes/*/memory-state.json")):
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            states.append(data)
    return states
