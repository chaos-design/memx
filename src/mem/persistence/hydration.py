"""Hydrate in-memory adapters from persisted MemX snapshots."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from ..embedding.vector import embed_text, tokenize
from ..memory.models import (
    ConflictAction,
    ConflictRecord,
    ConflictSeverity,
    ConflictType,
    ConsolidationInboxItem,
    EdgeType,
    EpisodicMemory,
    GraphEdge,
    GraphNode,
    InboxStatus,
    InsightStatus,
    MemoryIdentity,
    MemoryStatus,
    MemoryType,
    Message,
    NodeType,
    Role,
    SemanticFact,
    WorkingMemory,
)


def restore_scope_state(memory: Any, state: Mapping[str, Any]) -> Dict[str, Any]:
    """Restore one persisted scope into an AgentMemory-compatible object.

    输入:
        memory: AgentMemory-compatible instance with in-memory adapters.
        state: read_stored_state 返回的 scope snapshot。
    输出:
        dict: 每个层级恢复的记录数量摘要。
    示例:
        示例输入: restore_scope_state(memory, {"scope_id": "scope", "l2": []})
        示例输出: {"scope_id": "scope", "l2_records": 0, ...}
    """
    scope_id = str(state.get("scope_id", "default"))
    return {
        "scope_id": scope_id,
        "l0_messages": _restore_l0(memory.l0, scope_id, state.get("l0", {})),
        "l1_sessions": _restore_l1(memory.l1, scope_id, state.get("l1", [])),
        "l2_records": _restore_l2(memory.l2, memory.config, scope_id, state),
        "l3_facts": _restore_l3(memory.l3, memory.config, scope_id, state),
        "l4_nodes": _restore_l4(memory.l4, scope_id, state),
        "inbox_items": _restore_inbox(memory.inbox, scope_id, state.get("inbox", [])),
    }


def _restore_l0(buffer: Any, scope_id: str, raw_l0: Any) -> int:
    """Restore L0 raw message windows.

    输入:
        buffer: ConversationBuffer-compatible adapter.
        scope_id: 当前作用域 ID。
        raw_l0: snapshot 中的 l0 字典。
    输出:
        int: 恢复的消息数量。
    示例:
        示例输入: _restore_l0(buffer, "scope", {"s1": []})
        示例输出: 0
    """
    _clear_scoped_sessions(buffer, scope_id)
    if not isinstance(raw_l0, Mapping):
        return 0
    restored = 0
    for raw_messages in raw_l0.values():
        if not isinstance(raw_messages, list):
            continue
        messages = [_message_from_dict(item, scope_id) for item in raw_messages]
        if not messages:
            continue
        identity = messages[0].identity()
        key = identity.scoped_session_key()
        buffer._identities[key] = identity
        buffer._messages[key] = messages
        buffer._turns[key] = max(message.turn_id for message in messages)
        restored += len(messages)
    return restored


def _restore_l1(manager: Any, scope_id: str, raw_l1: Any) -> int:
    """Restore L1 working memory snapshots.

    输入:
        manager: WorkingMemoryManager-compatible adapter.
        scope_id: 当前作用域 ID。
        raw_l1: snapshot 中的 l1 列表。
    输出:
        int: 恢复的 L1 session 数量。
    示例:
        示例输入: _restore_l1(manager, "scope", [])
        示例输出: 0
    """
    _clear_scoped_sessions(manager, scope_id)
    if not isinstance(raw_l1, list):
        return 0
    restored = 0
    for item in raw_l1:
        if not isinstance(item, Mapping):
            continue
        session_id = str(item.get("session_id", "default"))
        item_scope = str(item.get("scope_id", scope_id))
        identity = MemoryIdentity.from_parts(session_id, item_scope)
        key = identity.scoped_session_key()
        manager._identities[key] = identity
        manager._store[key] = WorkingMemory(
            session_id=session_id,
            scope_id=item_scope,
            rolling_summary=str(item.get("rolling_summary", "")),
            open_slots=list(item.get("open_slots", [])),
            mentioned_entities=list(item.get("mentioned_entities", [])),
            token_used=int(item.get("token_used", 0)),
            last_compress_ts=float(item.get("last_compress_ts", 0.0)),
        )
        restored += 1
    return restored


def _restore_l2(
    store: Any,
    config: Any,
    scope_id: str,
    state: Mapping[str, Any],
) -> int:
    """Restore L2 episodic records and sparse indexes.

    输入:
        store: EpisodicStore-compatible adapter.
        config: MemoryConfig-compatible settings.
        scope_id: 当前作用域 ID。
        state: scope snapshot。
    输出:
        int: 恢复的 L2 记录数量。
    示例:
        示例输入: _restore_l2(store, config, "scope", {"l2": []})
        示例输出: 0
    """
    store._records[scope_id] = {}
    store._token_index[scope_id] = {}
    store._inverted_index[scope_id] = {}
    restored = 0
    for item in state.get("l2", []):
        if not isinstance(item, Mapping):
            continue
        record = _episodic_from_dict(item, config, scope_id)
        store._records[record.scope_id][record.mem_id] = record
        store._index_memory(
            record.scope_id,
            record.mem_id,
            frozenset(tokenize(record.text)),
        )
        restored += 1
    return restored


def _restore_l3(
    store: Any,
    config: Any,
    scope_id: str,
    state: Mapping[str, Any],
) -> int:
    """Restore L3 semantic facts and conflict logs.

    输入:
        store: SemanticStore-compatible adapter.
        config: MemoryConfig-compatible settings.
        scope_id: 当前作用域 ID。
        state: scope snapshot。
    输出:
        int: 恢复的 L3 fact 数量。
    示例:
        示例输入: _restore_l3(store, config, "scope", {"l3": {"facts": []}})
        示例输出: 0
    """
    store._facts[scope_id] = {}
    store._partition_index[scope_id].clear()
    store._conflict_log[scope_id] = []
    raw_l3 = state.get("l3", {})
    if not isinstance(raw_l3, Mapping):
        return 0
    restored = 0
    for item in raw_l3.get("facts", []):
        if not isinstance(item, Mapping):
            continue
        fact = _semantic_fact_from_dict(item, config, scope_id)
        store._facts[fact.scope_id].setdefault(fact.fact_key, []).append(fact)
        store._index_fact(fact)
        restored += 1
    for item in raw_l3.get("conflicts", []):
        if isinstance(item, Mapping):
            store._conflict_log[scope_id].append(_conflict_from_dict(item, scope_id))
    return restored


def _restore_l4(graph: Any, scope_id: str, state: Mapping[str, Any]) -> int:
    """Restore L4 graph nodes, edges, and label indexes.

    输入:
        graph: CognitiveGraph-compatible adapter.
        scope_id: 当前作用域 ID。
        state: scope snapshot。
    输出:
        int: 恢复的 L4 节点数量。
    示例:
        示例输入: _restore_l4(graph, "scope", {"l4": {"nodes": [], "edges": []}})
        示例输出: 0
    """
    graph._nodes[scope_id] = {}
    graph._edges[scope_id] = []
    graph._label_index[scope_id] = {}
    raw_l4 = state.get("l4", {})
    if not isinstance(raw_l4, Mapping):
        return 0
    for item in raw_l4.get("nodes", []):
        if not isinstance(item, Mapping):
            continue
        node = _graph_node_from_dict(item, scope_id)
        graph._nodes[node.scope_id][node.node_id] = node
        key = f"{node.node_type.value}:{node.label.lower()}"
        graph._label_index[node.scope_id][key] = node.node_id
    for item in raw_l4.get("edges", []):
        if isinstance(item, Mapping):
            edge = _graph_edge_from_dict(item, scope_id)
            graph._edges[edge.scope_id].append(edge)
    return len(graph._nodes.get(scope_id, {}))


def _restore_inbox(inbox: Any, scope_id: str, raw_inbox: Any) -> int:
    """Restore consolidation inbox items.

    输入:
        inbox: InMemoryInbox-compatible adapter.
        scope_id: 当前作用域 ID。
        raw_inbox: snapshot 中的 inbox 列表。
    输出:
        int: 恢复的 inbox item 数量。
    示例:
        示例输入: _restore_inbox(inbox, "scope", [])
        示例输出: 0
    """
    inbox._items[scope_id] = {}
    if not isinstance(raw_inbox, list):
        return 0
    for item in raw_inbox:
        if not isinstance(item, Mapping):
            continue
        inbox_item = _inbox_item_from_dict(item, scope_id)
        inbox._items[inbox_item.scope_id][inbox_item.item_id] = inbox_item
    return len(inbox._items.get(scope_id, {}))


def _clear_scoped_sessions(adapter: Any, scope_id: str) -> None:
    """Clear L0/L1 session state for one scope before hydration.

    输入:
        adapter: 带 _identities 的短期记忆 Adapter。
        scope_id: 需要清理的作用域 ID。
    输出:
        None。
    示例:
        示例输入: _clear_scoped_sessions(buffer, "scope")
        示例输出: None
    """
    for key, identity in list(adapter._identities.items()):
        if identity.scope_id != scope_id:
            continue
        adapter._identities.pop(key, None)
        if hasattr(adapter, "_messages"):
            adapter._messages.pop(key, None)
            adapter._turns.pop(key, None)
            adapter._evicted.pop(key, None)
        if hasattr(adapter, "_store"):
            adapter._store.pop(key, None)


def _message_from_dict(item: Mapping[str, Any], scope_id: str) -> Message:
    """Build a Message model from persisted JSON fields.

    输入:
        item: Message.to_dict 输出。
        scope_id: 缺省作用域 ID。
    输出:
        Message: 恢复后的 L0 消息。
    示例:
        示例输入: _message_from_dict({"content": "hi", "role": "user"}, "scope")
        示例输出: Message(...)
    """
    return Message(
        turn_id=int(item.get("turn_id", 1)),
        role=Role(str(item.get("role", Role.USER.value))),
        content=str(item.get("content", "")),
        ts=float(item.get("ts", 0.0)),
        token_len=int(item.get("token_len", 0)),
        session_id=str(item.get("session_id", "default")),
        scope_id=str(item.get("scope_id", scope_id)),
    )


def _episodic_from_dict(
    item: Mapping[str, Any],
    config: Any,
    scope_id: str,
) -> EpisodicMemory:
    """Build an EpisodicMemory model from persisted JSON fields.

    输入:
        item: EpisodicMemory.to_dict 输出。
        config: MemoryConfig-compatible settings.
        scope_id: 缺省作用域 ID。
    输出:
        EpisodicMemory: 恢复后的 L2 记录。
    示例:
        示例输入: _episodic_from_dict({"mem_id": "m", "text": "x"}, config, "s")
        示例输出: EpisodicMemory(...)
    """
    text = str(item.get("text", ""))
    return EpisodicMemory(
        mem_id=str(item.get("mem_id", "")),
        embedding=embed_text(text, config.embedding_dimensions),
        text=text,
        importance=int(item.get("importance", 5)),
        ts_create=float(item.get("ts_create", 0.0)),
        ts_last_access=float(item.get("ts_last_access", item.get("ts_create", 0.0))),
        scope_id=str(item.get("scope_id", scope_id)),
        access_count=int(item.get("access_count", 0)),
        stability=float(item.get("stability", config.initial_stability_seconds)),
        status=MemoryStatus(str(item.get("status", MemoryStatus.ACTIVE.value))),
        source_ids=list(item.get("source_ids", [])),
        mem_type=MemoryType(str(item.get("mem_type", MemoryType.EPISODIC.value))),
    )


def _semantic_fact_from_dict(
    item: Mapping[str, Any],
    config: Any,
    scope_id: str,
) -> SemanticFact:
    """Build a SemanticFact model from persisted JSON fields.

    输入:
        item: SemanticFact.to_dict 输出。
        config: MemoryConfig-compatible settings.
        scope_id: 缺省作用域 ID。
    输出:
        SemanticFact: 恢复后的 L3 事实。
    示例:
        示例输入: _semantic_fact_from_dict({"fact_key": "k"}, config, "scope")
        示例输出: SemanticFact(...)
    """
    fact = SemanticFact(
        fact_key=str(item.get("fact_key", "")),
        scope_id=str(item.get("scope_id", scope_id)),
        value=item.get("value"),
        confidence=float(item.get("confidence", 0.9)),
        evidence_ids=list(item.get("evidence_ids", [])),
        version=int(item.get("version", 1)),
        ts_update=float(item.get("ts_update", 0.0)),
        evidence_hash=str(item.get("evidence_hash", "")),
        is_temporal=bool(item.get("is_temporal", False)),
        valid_from=item.get("valid_from"),
        valid_until=item.get("valid_until"),
        mem_type=MemoryType(str(item.get("mem_type", MemoryType.SEMANTIC.value))),
        partition=str(item.get("partition", "semantic")),
    )
    fact.embedding = embed_text(fact.content_text(), config.embedding_dimensions)
    return fact


def _conflict_from_dict(item: Mapping[str, Any], scope_id: str) -> ConflictRecord:
    """Build a ConflictRecord model from persisted JSON fields.

    输入:
        item: ConflictRecord.to_dict 输出。
        scope_id: 缺省作用域 ID。
    输出:
        ConflictRecord: 恢复后的冲突审计记录。
    示例:
        示例输入: _conflict_from_dict({"conflict_id": "c"}, "scope")
        示例输出: ConflictRecord(...)
    """
    return ConflictRecord(
        conflict_id=str(item.get("conflict_id", "")),
        scope_id=str(item.get("scope_id", scope_id)),
        fact_key=item.get("fact_key"),
        conflict_type=ConflictType(str(item.get("conflict_type"))),
        severity=ConflictSeverity(str(item.get("severity"))),
        old_value=item.get("old_value"),
        new_value=item.get("new_value"),
        policy_hit=str(item.get("policy_hit", "")),
        action=ConflictAction(str(item.get("action"))),
        resolved_to=item.get("resolved_to"),
        ts=float(item.get("ts", 0.0)),
    )


def _graph_node_from_dict(item: Mapping[str, Any], scope_id: str) -> GraphNode:
    """Build a GraphNode model from persisted JSON fields.

    输入:
        item: GraphNode.to_dict 输出。
        scope_id: 缺省作用域 ID。
    输出:
        GraphNode: 恢复后的 L4 节点。
    示例:
        示例输入: _graph_node_from_dict({"id": "n", "label": "x"}, "scope")
        示例输出: GraphNode(...)
    """
    return GraphNode(
        node_id=str(item.get("id", "")),
        node_type=NodeType(str(item.get("type", NodeType.ENTITY.value))),
        label=str(item.get("label", "")),
        scope_id=str(item.get("scope_id", scope_id)),
        salience=float(item.get("salience", 0.5)),
        evidence_ids=list(item.get("evidence_ids", [])),
        status=InsightStatus(str(item.get("status", InsightStatus.ACTIVE.value))),
        mem_type=MemoryType(str(item.get("mem_type", MemoryType.SEMANTIC.value))),
    )


def _graph_edge_from_dict(item: Mapping[str, Any], scope_id: str) -> GraphEdge:
    """Build a GraphEdge model from persisted JSON fields.

    输入:
        item: GraphEdge.to_dict 输出。
        scope_id: 缺省作用域 ID。
    输出:
        GraphEdge: 恢复后的 L4 边。
    示例:
        示例输入: _graph_edge_from_dict({"source": "a", "target": "b"}, "scope")
        示例输出: GraphEdge(...)
    """
    return GraphEdge(
        source_id=str(item.get("source", "")),
        target_id=str(item.get("target", "")),
        edge_type=EdgeType(str(item.get("type", EdgeType.SIMILAR.value))),
        scope_id=str(item.get("scope_id", scope_id)),
        weight=float(item.get("weight", 0.5)),
    )


def _inbox_item_from_dict(
    item: Mapping[str, Any],
    scope_id: str,
) -> ConsolidationInboxItem:
    """Build a ConsolidationInboxItem model from persisted JSON fields.

    输入:
        item: ConsolidationInboxItem.to_dict 输出。
        scope_id: 缺省作用域 ID。
    输出:
        ConsolidationInboxItem: 恢复后的固化任务。
    示例:
        示例输入: _inbox_item_from_dict({"item_id": "i", "mem_id": "m"}, "scope")
        示例输出: ConsolidationInboxItem(...)
    """
    status = InboxStatus(str(item.get("status", InboxStatus.PENDING.value)))
    if status == InboxStatus.PROCESSING:
        status = InboxStatus.PENDING
    return ConsolidationInboxItem(
        item_id=str(item.get("item_id", "")),
        scope_id=str(item.get("scope_id", scope_id)),
        mem_id=str(item.get("mem_id", "")),
        text=str(item.get("text", "")),
        priority=float(item.get("priority", 0.0)),
        ts_enqueue=float(item.get("ts_enqueue", 0.0)),
        mem_type_hint=MemoryType(
            str(item.get("mem_type_hint", MemoryType.EPISODIC.value))
        ),
        status=status,
        retry_count=int(item.get("retry_count", 0)),
        last_error=item.get("last_error"),
    )
