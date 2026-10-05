"""Port contracts for decoupled Agent memory backends."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Protocol, Set

from .models import (
    ConsolidationInboxItem,
    EpisodicMemory,
    GraphEdge,
    GraphNode,
    MemoryIdentity,
    MemoryStatus,
    MemoryType,
    Message,
    SemanticFact,
    WorkingMemory,
)


class L0BufferPort(Protocol):
    """Port for short-term raw conversation buffering."""

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        ts: Optional[float] = None,
        scope_id: str = "default",
    ) -> Message:
        """Append one raw message.

        输入:
            session_id: 会话 ID。
            role: 消息角色。
            content: 消息正文。
            ts: 可选时间戳。
            scope_id: 作用域 ID。
        输出:
            Message: 已写入的 L0 消息。
        示例:
            示例输入: port.append("s1", "user", "hi", scope_id="t1")
            示例输出: Message(session_id="s1", scope_id="t1", ...)
        """
        ...

    def drain_evicted(
        self, session_id: str, scope_id: str = "default"
    ) -> List[Message]:
        """Return and clear evicted messages for compensation compression.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            list[Message]: 被环形窗口淘汰的消息。
        示例:
            示例输入: port.drain_evicted("s1", "t1")
            示例输出: [Message(...)] 或 []。
        """
        ...

    def should_compress(self, session_id: str, scope_id: str = "default") -> bool:
        """Return whether L0 should be compressed into L1.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            bool: True 表示达到压缩阈值。
        示例:
            示例输入: port.should_compress("s1", "t1")
            示例输出: True
        """
        ...

    def flush_to_l1(self, session_id: str, scope_id: str = "default") -> List[Message]:
        """Drain the active L0 window for L1 compression.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            list[Message]: 待压缩消息。
        示例:
            示例输入: port.flush_to_l1("s1", "t1")
            示例输出: [Message(...)]。
        """
        ...

    def active_sessions(self, scope_id: str = "default") -> List[MemoryIdentity]:
        """List active L0 sessions for diagnostics.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[MemoryIdentity]: 活跃身份列表。
        示例:
            示例输入: port.active_sessions("t1")
            示例输出: [MemoryIdentity(...)]。
        """
        ...

    def snapshot(self, scope_id: Optional[str] = None) -> Dict[str, List[dict]]:
        """Return a serializable L0 snapshot.

        输入:
            scope_id: 可选作用域 ID。
        输出:
            dict: session_id 到消息字典列表的映射。
        示例:
            示例输入: port.snapshot("t1")
            示例输出: {"s1": [{"role": "user", ...}]}。
        """
        ...


class L1WorkingMemoryPort(Protocol):
    """Port for structured working memory."""

    def compress(
        self,
        session_id: str,
        messages: List[Message],
        scope_id: str = "default",
    ) -> WorkingMemory:
        """Compress L0 messages into L1.

        输入:
            session_id: 会话 ID。
            messages: L0 消息列表。
            scope_id: 作用域 ID。
        输出:
            WorkingMemory: 更新后的 L1 快照。
        示例:
            示例输入: port.compress("s1", [Message(...)], scope_id="t1")
            示例输出: WorkingMemory(session_id="s1", scope_id="t1", ...)
        """
        ...

    def get_active_context(
        self,
        session_id: str,
        scope_id: str = "default",
    ) -> WorkingMemory:
        """Return the active L1 context.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            WorkingMemory: 当前上下文对象。
        示例:
            示例输入: port.get_active_context("s1", "t1")
            示例输出: WorkingMemory(...)。
        """
        ...

    def promote(
        self, session_id: str, scope_id: str = "default"
    ) -> List[Dict[str, Any]]:
        """Return closed slots that should be promoted into L2.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            list[dict]: closed slot 列表。
        示例:
            示例输入: port.promote("s1", "t1")
            示例输出: [{"text": "..."}] 或 []。
        """
        ...

    def active_sessions(self, scope_id: str = "default") -> List[MemoryIdentity]:
        """List active L1 sessions for diagnostics.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[MemoryIdentity]: 活跃身份列表。
        示例:
            示例输入: port.active_sessions("t1")
            示例输出: [MemoryIdentity(...)]。
        """
        ...


class L2EpisodicPort(Protocol):
    """Port for long-term episodic vector memory."""

    def promote(
        self,
        text: str,
        scope_id: str,
        importance: int,
        source_ids: Optional[List[str]] = None,
        mem_id: Optional[str] = None,
        ts: Optional[float] = None,
        mem_type: MemoryType = MemoryType.EPISODIC,
    ) -> EpisodicMemory:
        """Promote one text into L2.

        输入:
            text: 记忆正文。
            scope_id: 作用域 ID。
            importance: 重要性分。
            source_ids: 来源 ID 列表。
            mem_id: 可选幂等 ID。
            ts: 可选时间戳。
            mem_type: 逻辑记忆类型。
        输出:
            EpisodicMemory: 写入后的记录。
        示例:
            示例输入: port.promote("remember x", "t1", 8)
            示例输出: EpisodicMemory(scope_id="t1", ...)
        """
        ...

    def retrieve(
        self,
        query: str,
        scope_id: str,
        k: int,
        now_ts: Optional[float] = None,
        include_archived: bool = False,
    ) -> List[EpisodicMemory]:
        """Retrieve L2 candidates.

        输入:
            query: 查询文本。
            scope_id: 作用域 ID。
            k: 返回数量。
            now_ts: 可选当前时间戳。
            include_archived: 是否包含归档记忆。
        输出:
            list[EpisodicMemory]: 排序后的候选。
        示例:
            示例输入: port.retrieve("memory", "t1", 3)
            示例输出: [EpisodicMemory(...)]。
        """
        ...

    def reinforce(
        self,
        mem_id: str,
        scope_id: str,
        now_ts: Optional[float] = None,
    ) -> Optional[EpisodicMemory]:
        """Reinforce one retrieved L2 memory.

        输入:
            mem_id: L2 记忆 ID。
            scope_id: 作用域 ID。
            now_ts: 可选当前时间戳。
        输出:
            EpisodicMemory | None: 被更新记录或 None。
        示例:
            示例输入: port.reinforce("m1", "t1")
            示例输出: EpisodicMemory(access_count=1, ...)。
        """
        ...

    def decay_sweep(
        self,
        scope_id: str,
        now_ts: Optional[float] = None,
    ) -> Dict[str, object]:
        """Run L2 dynamic forgetting.

        输入:
            scope_id: 作用域 ID。
            now_ts: 可选当前时间戳。
        输出:
            dict: checked、archived、deleted 等统计。
        示例:
            示例输入: port.decay_sweep("t1")
            示例输出: {"checked": 1.0, "archived": 0.0, ...}
        """
        ...

    def update(
        self,
        mem_id: str,
        scope_id: str,
        text: Optional[str] = None,
        importance: Optional[int] = None,
    ) -> EpisodicMemory:
        """Update editable L2 fields.

        输入:
            mem_id: L2 记忆 ID。
            scope_id: 作用域 ID。
            text: 可选新正文。
            importance: 可选重要性。
        输出:
            EpisodicMemory: 更新后的记录。
        示例:
            示例输入: port.update("m1", "t1", text="new")
            示例输出: EpisodicMemory(text="new", ...)。
        """
        ...

    def get(self, mem_id: str, scope_id: str) -> Optional[EpisodicMemory]:
        """Get one L2 record by ID.

        输入:
            mem_id: L2 记忆 ID。
            scope_id: 作用域 ID。
        输出:
            EpisodicMemory | None: 命中记录。
        示例:
            示例输入: port.get("m1", "t1")
            示例输出: EpisodicMemory(...) 或 None。
        """
        ...

    def all_records(
        self,
        scope_id: str,
        statuses: Optional[Iterable[MemoryStatus]] = None,
    ) -> List[EpisodicMemory]:
        """List L2 records for a scope.

        输入:
            scope_id: 作用域 ID。
            statuses: 可选状态集合。
        输出:
            list[EpisodicMemory]: L2 记录列表。
        示例:
            示例输入: port.all_records("t1", {MemoryStatus.ACTIVE})
            示例输出: [EpisodicMemory(...)]。
        """
        ...

    def occupancy(self, scope_id: str) -> float:
        """Return active L2 occupancy.

        输入:
            scope_id: 作用域 ID。
        输出:
            float: active_count / capacity。
        示例:
            示例输入: port.occupancy("t1")
            示例输出: 0.01
        """
        ...

    def last_retrieval_stats(self) -> Dict[str, object]:
        """Return the latest L2 retrieval diagnostics.

        输入:
            self: L2 Port。
        输出:
            dict: 候选池和排序诊断。
        示例:
            示例输入: port.last_retrieval_stats()
            示例输出: {"candidate_count": 3, ...}
        """
        ...


class L3SemanticPort(Protocol):
    """Port for semantic facts and conflict governance."""

    def upsert(
        self,
        fact_key: str,
        scope_id: str,
        value: Any,
        confidence: float,
        evidence_ids: Optional[List[str]] = None,
        ts_update: Optional[float] = None,
        mem_type: MemoryType = MemoryType.SEMANTIC,
        partition: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upsert one L3 fact.

        输入:
            fact_key: 事实键。
            scope_id: 作用域 ID。
            value: 事实值。
            confidence: 置信度。
            evidence_ids: 证据 ID 列表。
            ts_update: 可选更新时间。
            mem_type: 逻辑记忆类型。
            partition: 可选分区。
        输出:
            dict: action、version 等写入结果。
        示例:
            示例输入: port.upsert("user.lang", "t1", "zh", 0.9)
            示例输出: {"action": "created", "version": 1, ...}
        """
        ...

    def query_relevant(
        self,
        query: str,
        scope_id: str,
        k: int = 8,
        partition: Optional[str] = None,
        mem_type: Optional[MemoryType] = None,
    ) -> List[SemanticFact]:
        """Retrieve relevant L3 facts.

        输入:
            query: 查询文本。
            scope_id: 作用域 ID。
            k: 返回数量。
            partition: 可选分区。
            mem_type: 可选记忆类型。
        输出:
            list[SemanticFact]: 相关事实列表。
        示例:
            示例输入: port.query_relevant("lang", "t1")
            示例输出: [SemanticFact(...)]。
        """
        ...

    def degrade_orphaned_evidence(
        self,
        scope_id: str,
        affected_evidence_ids: List[str],
    ) -> int:
        """Lower confidence for facts whose evidence became stale.

        输入:
            scope_id: 作用域 ID。
            affected_evidence_ids: 被归档或删除的证据 ID。
        输出:
            int: 被降置信事实数量。
        示例:
            示例输入: port.degrade_orphaned_evidence("t1", ["m1"])
            示例输出: 1
        """
        ...

    def prune_low_confidence(self, scope_id: str) -> int:
        """Remove low-confidence facts.

        输入:
            scope_id: 作用域 ID。
        输出:
            int: 被删除 fact_key 数。
        示例:
            示例输入: port.prune_low_confidence("t1")
            示例输出: 1
        """
        ...

    def all_facts(self, scope_id: str) -> List[SemanticFact]:
        """List latest L3 facts.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[SemanticFact]: 最新事实列表。
        示例:
            示例输入: port.all_facts("t1")
            示例输出: [SemanticFact(...)]。
        """
        ...

    def conflict_log(
        self,
        scope_id: str,
        fact_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return conflict audit records.

        输入:
            scope_id: 作用域 ID。
            fact_key: 可选事实键。
        输出:
            list[dict]: 冲突日志。
        示例:
            示例输入: port.conflict_log("t1", "user.lang")
            示例输出: [{"action": "replace", ...}]。
        """
        ...


class L4GraphPort(Protocol):
    """Port for cognitive graph memory."""

    def add_insight(
        self,
        scope_id: str,
        label: str,
        evidence_ids: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        salience: float = 0.5,
        mem_type: MemoryType = MemoryType.SEMANTIC,
    ) -> GraphNode:
        """Add or update an L4 insight.

        输入:
            scope_id: 作用域 ID。
            label: 洞察标签。
            evidence_ids: 证据 ID。
            entities: 相关实体。
            salience: 显著度。
            mem_type: 逻辑记忆类型。
        输出:
            GraphNode: 洞察节点。
        示例:
            示例输入: port.add_insight("t1", "Agent memory")
            示例输出: GraphNode(label="Agent memory", ...)。
        """
        ...

    def graph_query(
        self, scope_id: str, query: str, k: int = 8
    ) -> Dict[str, List[dict]]:
        """Query L4 graph context.

        输入:
            scope_id: 作用域 ID。
            query: 查询文本。
            k: 节点数量上限。
        输出:
            dict: nodes 和 edges。
        示例:
            示例输入: port.graph_query("t1", "Agent")
            示例输出: {"nodes": [...], "edges": [...]}。
        """
        ...

    def subgraph_for_context(
        self,
        scope_id: str,
        entities: Optional[List[str]],
        k: int = 8,
    ) -> Dict[str, List[dict]]:
        """Return a graph subcontext for entities.

        输入:
            scope_id: 作用域 ID。
            entities: 实体标签列表。
            k: 节点数量上限。
        输出:
            dict: nodes 和 edges。
        示例:
            示例输入: port.subgraph_for_context("t1", ["Agent"])
            示例输出: {"nodes": [...], "edges": [...]}。
        """
        ...

    def mark_evidence_stale(self, scope_id: str, evidence_ids: List[str]) -> int:
        """Mark insights stale once none of their evidence is valid.

        判死条件是有效证据为空，而非任一证据失效；status 由证据集合推导，
        证据重新被观察到时应自动复活。

        输入:
            scope_id: 作用域 ID。
            evidence_ids: 失效证据 ID。
        输出:
            int: 本次新变为 superseded 的节点数。
        示例:
            示例输入: port.mark_evidence_stale("t1", ["m1"])
            示例输出: 1
        """
        ...

    def stale_evidence_ids(self, scope_id: str) -> Set[str]:
        """Return the recorded stale evidence IDs for one scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            set[str]: 已失效证据 ID 集合。
        示例:
            示例输入: port.stale_evidence_ids("t1")
            示例输出: {"m1"}
        """
        ...

    def prune(self, scope_id: str) -> int:
        """Prune low-salience isolated graph nodes.

        输入:
            scope_id: 作用域 ID。
        输出:
            int: 被剪枝节点数。
        示例:
            示例输入: port.prune("t1")
            示例输出: 0
        """
        ...

    def audit(self, scope_id: str, repair: bool = True) -> Dict[str, int]:
        """Audit L4 graph consistency.

        输入:
            scope_id: 作用域 ID。
            repair: 是否修复孤儿边。
        输出:
            dict: checked_nodes、orphan_edges 等统计。
        示例:
            示例输入: port.audit("t1", repair=True)
            示例输出: {"orphan_edges": 0, ...}
        """
        ...

    def all_nodes(self, scope_id: str) -> List[GraphNode]:
        """List graph nodes for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[GraphNode]: 节点列表。
        示例:
            示例输入: port.all_nodes("t1")
            示例输出: [GraphNode(...)]。
        """
        ...

    def all_edges(self, scope_id: str) -> List[GraphEdge]:
        """List graph edges for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[GraphEdge]: 边列表。
        示例:
            示例输入: port.all_edges("t1")
            示例输出: [GraphEdge(...)]。
        """
        ...


class InboxPort(Protocol):
    """Port for asynchronous consolidation inboxes."""

    def enqueue(
        self,
        memory: EpisodicMemory,
        mem_type_hint: Optional[MemoryType] = None,
        now_ts: Optional[float] = None,
    ) -> ConsolidationInboxItem:
        """Enqueue one L2 memory for consolidation.

        输入:
            memory: L2 记忆对象。
            mem_type_hint: 可选类型提示。
            now_ts: 可选入队时间。
        输出:
            ConsolidationInboxItem: 队列条目。
        示例:
            示例输入: port.enqueue(memory)
            示例输出: ConsolidationInboxItem(status=InboxStatus.PENDING, ...)
        """
        ...

    def pull(self, scope_id: str, limit: int = 50) -> List[ConsolidationInboxItem]:
        """Pull pending inbox items.

        输入:
            scope_id: 作用域 ID。
            limit: 最大条目数。
        输出:
            list[ConsolidationInboxItem]: 待处理条目。
        示例:
            示例输入: port.pull("t1", 10)
            示例输出: [ConsolidationInboxItem(...)]。
        """
        ...

    def mark_done(self, scope_id: str, item_id: str) -> None:
        """Mark an inbox item as done.

        输入:
            scope_id: 作用域 ID。
            item_id: 条目 ID。
        输出:
            None。
        示例:
            示例输入: port.mark_done("t1", "ci_x")
            示例输出: None。
        """
        ...

    def mark_failed(self, scope_id: str, item_id: str, error: str) -> None:
        """Mark an inbox item as failed or retryable.

        输入:
            scope_id: 作用域 ID。
            item_id: 条目 ID。
            error: 失败原因。
        输出:
            None。
        示例:
            示例输入: port.mark_failed("t1", "ci_x", "timeout")
            示例输出: None。
        """
        ...

    def pending_count(self, scope_id: str) -> int:
        """Return pending inbox count.

        输入:
            scope_id: 作用域 ID。
        输出:
            int: pending 条目数。
        示例:
            示例输入: port.pending_count("t1")
            示例输出: 3
        """
        ...

    def stats(self, scope_id: str) -> Dict[str, int]:
        """Return inbox status counts.

        输入:
            scope_id: 作用域 ID。
        输出:
            dict: status 到数量的映射。
        示例:
            示例输入: port.stats("t1")
            示例输出: {"pending": 1, "done": 2, ...}
        """
        ...

    def snapshot(self, scope_id: str) -> List[Dict[str, object]]:
        """Return a serializable inbox snapshot.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[dict]: 队列快照。
        示例:
            示例输入: port.snapshot("t1")
            示例输出: [{"item_id": "ci_x", ...}]。
        """
        ...


class SnapshotStorePort(Protocol):
    """Port for scope state snapshots."""

    def write_scope_state(self, scope_id: str, state: Dict[str, Any]) -> str:
        """Write a scope state snapshot.

        输入:
            scope_id: 作用域 ID。
            state: 可 JSON 序列化状态。
        输出:
            str: 状态文件或对象路径。
        示例:
            示例输入: port.write_scope_state("t1", {"scope_id": "t1"})
            示例输出: ".memories/scopes/t1/memory-state.json"
        """
        ...

    def read_scope_state(self, scope_id: str) -> Optional[Dict[str, Any]]:
        """Read a scope state snapshot.

        输入:
            scope_id: 作用域 ID。
        输出:
            dict | None: 状态快照。
        示例:
            示例输入: port.read_scope_state("t1")
            示例输出: {"scope_id": "t1"} 或 None。
        """
        ...

    def scope_state_relative_path(self, scope_id: str) -> str:
        """Return a scope state path.

        输入:
            scope_id: 作用域 ID。
        输出:
            str: 项目相对路径或对象路径。
        示例:
            示例输入: port.scope_state_relative_path("t1")
            示例输出: ".memories/scopes/t1/memory-state.json"
        """
        ...


class LLMGatewayPort(Protocol):
    """Port for external model and embedding gateways."""

    def decide_json(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Return a schema-constrained model decision.

        输入:
            prompt: 决策提示词。
            schema: JSON Schema。
        输出:
            dict: 结构化决策。
        示例:
            示例输入: gateway.decide_json("classify", {"type": "object"})
            示例输出: {"op": "skip"}。
        """
        ...

    def embed(self, text: str) -> List[float]:
        """Return an embedding vector.

        输入:
            text: 待向量化文本。
        输出:
            list[float]: embedding 向量。
        示例:
            示例输入: gateway.embed("Agent memory")
            示例输出: [0.1, 0.2, ...]。
        """
        ...

    def healthcheck(self) -> Dict[str, Any]:
        """Return model gateway health diagnostics.

        输入:
            self: LLM Gateway Port。
        输出:
            dict: 健康状态。
        示例:
            示例输入: gateway.healthcheck()
            示例输出: {"status": "ok"}。
        """
        ...
