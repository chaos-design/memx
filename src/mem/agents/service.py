"""Unified Agent memory service."""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from ..adapters import MemoryBackendBundle, build_memory_backend
from ..config.loader import load_memory_config
from ..config.settings import MemoryConfig
from ..constants import (
    FORGET_MODE_DECAY,
    FORGET_MODE_EXPIRE,
    FORGET_MODE_HARD,
    KEY_VALUE_MEMORY_PATTERN,
    PARTITION_PREFERENCE,
    PARTITION_PROCEDURAL,
    PARTITION_SEMANTIC,
)
from ..embedding.scoring import f1_importance, rule_signal_score, user_emphasis_score
from ..exceptions import ProtectedMemoryError
from ..memory.models import EpisodicMemory, MemoryIdentity, MemoryStatus, MemoryType
from ..persistence.manager import PersistenceManager
from ..utils.hashing import short_hash
from ..utils.text import extract_entities, insight_label, is_explicit_memory
from ..utils.validation import validate_recall_k
from .consolidation import ConsolidationAgent
from .prompts import render_episodes_context, render_facts_context
from .recall import RecallAgent

# 显式 key=value 记忆提取规则，支持中文“记住”和英文 remember 前缀。
KEY_VALUE_MEMORY = re.compile(KEY_VALUE_MEMORY_PATTERN, re.I)


class AgentMemory:
    """Facade implementing observe, recall, reflect, and forget operations."""

    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        backend: Optional[MemoryBackendBundle] = None,
    ) -> None:
        """Initialize all memory layers.

        输入:
            config: 可选配置；None 使用默认配置。
            backend: 可选 Port/Adapter 后端组合；None 时按 config.backend_mode 构建。
        输出:
            None。
        示例:
            示例输入: AgentMemory(MemoryConfig(flush_turns=1))
            示例输出: AgentMemory 实例，L0-L4 Port 已初始化。
        """
        self.config = config or load_memory_config()
        self.backend = backend or build_memory_backend(self.config)

        # L0 原始对话缓冲 Port，默认内存实现，生产可替换为 Redis Adapter。
        self.l0 = self.backend.l0

        # L1 工作记忆 Port，负责滚动摘要、open slot 和实体候选。
        self.l1 = self.backend.l1

        # L2 情景记忆 Port，默认内存向量实现，生产可替换为 pgvector Adapter。
        self.l2 = self.backend.l2

        # L3 语义事实 Port，负责事实版本链和冲突治理。
        self.l3 = self.backend.l3

        # L4 认知图谱 Port，默认内存图实现，生产可替换为 Neo4j Adapter。
        self.l4 = self.backend.l4

        # 项目本地文件存储或生产快照存储 Adapter。
        self.storage = self.backend.storage

        # 显式持久化协调器，recall 默认只标记 dirty，不再同步写整作用域快照。
        self.persistence = PersistenceManager(self.storage)

        # 写后固化 inbox Port，生产部署可替换为 Redis/Kafka 等外部队列。
        self.inbox = self.backend.inbox

        # 统一 LLM Gateway Port；当前确定性实现不把 LLM 放入关键路径。
        self.llm_gateway = self.backend.llm_gateway

        # 在线召回编排组件，保持零 LLM 关键路径。
        self.recall_agent = RecallAgent(
            config=self.config,
            l2=self.l2,
            l3=self.l3,
            l4=self.l4,
            mark_dirty=self.persistence.mark_dirty,
        )

        # 异步固化组件，消费 inbox 后写 L3/L4。
        self.consolidation_agent = ConsolidationAgent(
            config=self.config,
            inbox=self.inbox,
            l2=self.l2,
            l3=self.l3,
            l4=self.l4,
            fact_extractor=self._fact_specs_from_memory,
            entity_extractor=self._entities_from_text,
            insight_labeler=self._insight_label,
            mark_stale_evidence=self._cascade_stale_evidence,
            mark_dirty=self.persistence.mark_dirty,
        )

    def observe(
        self,
        session_id: str,
        msg: Dict[str, Any],
        scope_id: str = "default",
    ) -> Dict[str, Any]:
        """Observe one message and optionally compress/promote it.

        输入:
            session_id: 会话 ID。
            msg: 包含 role、content、可选 ts 的消息字典。
            scope_id: 作用域 ID。
        输出:
            dict: mem_id、compress_triggered、l1_token_used。
        示例:
            示例输入:
                memory.observe("s1", {"role": "user", "content": "记住 x"})
            示例输出: {"mem_id": "...", "compress_triggered": False, ...}
        """
        message = self.l0.append(
            session_id=session_id,
            role=str(msg.get("role", "user")),
            content=str(msg["content"]),
            ts=msg.get("ts"),
            scope_id=scope_id,
        )
        promoted = []
        evicted = self.l0.drain_evicted(session_id, scope_id)
        evicted_compressed = bool(evicted)
        if evicted:
            self.l1.compress(session_id, evicted, scope_id=scope_id)
            promoted.extend(self._promote_l1_closed_slots(session_id, scope_id))
        if self._is_explicit_memory(message.content):
            memory = self._promote_text(
                text=message.content,
                scope_id=scope_id,
                source_ids=[message.source_id()],
                user_text=message.content,
                ts=message.ts,
            )
            promoted.append(memory.mem_id)
        compress_triggered = self.l0.should_compress(session_id, scope_id)
        if compress_triggered:
            promoted.extend(self._compress_and_promote(session_id, scope_id))
        active = self.l1.get_active_context(session_id, scope_id)
        storage_path = self._storage_path_after_write(scope_id)
        return {
            "mem_id": promoted[0] if promoted else None,
            "promoted": promoted,
            "inbox_enqueued": len(promoted),
            "inbox_pending": self.inbox.pending_count(scope_id),
            "compress_triggered": compress_triggered,
            "evicted_compressed": evicted_compressed,
            "l1_token_used": active.token_used,
            "storage_path": storage_path,
        }

    def recall(
        self,
        session_id: str,
        query: str,
        k: int = 8,
        entities: Optional[List[str]] = None,
        scope_id: str = "default",
        include_archived: bool = True,
    ) -> Dict[str, Any]:
        """Recall facts, episodes, and graph context.

        输入:
            session_id: 会话 ID。
            query: 查询文本。
            k: 返回数量。
            entities: 可选实体列表。
            scope_id: 作用域 ID。
            include_archived: 是否允许 archived 记忆被召回并复活。
        输出:
            dict: facts、episodes、subgraph、reinforced。
        示例:
            示例输入: memory.recall("s1", "语言偏好", k=3)
            示例输出: {"facts": [...], "episodes": [...], "subgraph": {...}, ...}
        """
        self._validate_k(k)
        result = self.recall_agent.recall(
            session_id=session_id,
            query=query,
            k=k,
            entities=entities,
            scope_id=scope_id,
            include_archived=include_archived,
        )
        if self.config.persist_on_recall and self.persistence.is_dirty(scope_id):
            result["storage_path"] = self.flush(scope_id)
        return result

    def get_context(
        self,
        session_id: str,
        query: Optional[str] = None,
        scope_id: str = "default",
    ) -> str:
        """Assemble L1 and optional recall context.

        输入:
            session_id: 会话 ID。
            query: 可选检索 query。
            scope_id: 作用域 ID。
        输出:
            str: 可直接放入 Agent prompt 的上下文。
        示例:
            示例输入: memory.get_context("s1", "偏好")
            示例输出:
                "Conversation Summary: ...\n"
                "Verified Facts: [...]\n"
                "Relevant Episodes: [...]"
        """
        parts = [self.l1.get_active_context(session_id, scope_id).to_context()]
        if query:
            recall_k = min(8, self.config.max_recall_k)
            recalled = self.recall(session_id, query, k=recall_k, scope_id=scope_id)
            facts = [item["value"] for item in recalled["facts"]]
            episodes = [item["text"] for item in recalled["episodes"]]
            facts_context = render_facts_context(facts)
            episodes_context = render_episodes_context(episodes)
            if facts_context:
                parts.append(facts_context)
            if episodes_context:
                parts.append(episodes_context)
        return "\n".join(part for part in parts if part)

    def upsert_fact(self, fact: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert an L3 fact through the unified interface.

        输入:
            fact: fact_key、value、confidence、evidence_ids、scope_id。
        输出:
            dict: fact_key、version、action。
        示例:
            示例输入: memory.upsert_fact({"fact_key": "user.lang", "value": "zh"})
            示例输出: {"fact_key": "user.lang", "version": 1, "action": "created"}
        """
        result = self.l3.upsert(
            fact_key=str(fact["fact_key"]),
            scope_id=str(fact.get("scope_id", "default")),
            value=fact["value"],
            confidence=float(fact.get("confidence", 0.9)),
            evidence_ids=list(fact.get("evidence_ids", [])),
            ts_update=fact.get("ts_update"),
            mem_type=self._memory_type_from_value(
                fact.get("mem_type", MemoryType.SEMANTIC)
            ),
            partition=fact.get("partition"),
        )
        self._cascade_stale_evidence(
            str(fact.get("scope_id", "default")),
            result.get("superseded_evidence_ids", []),
        )
        result["storage_path"] = self._storage_path_after_write(
            str(fact.get("scope_id", "default"))
        )
        return result

    def reflect(
        self,
        scope_id: str = "default",
        force: bool = False,
    ) -> Dict[str, Any]:
        """Consolidate episodic memories into L3 facts and L4 insights.

        输入:
            scope_id: 作用域 ID。
            force: 是否忽略 θ_reflect 强制执行。
        输出:
            dict: n_facts、n_insights、promoted_l4。
        示例:
            示例输入: memory.reflect("scope", force=True)
            示例输出: {"n_facts": 1, "n_insights": 1, "promoted_l4": ["..."]}
        """
        candidates = self.l2.all_records(scope_id, {MemoryStatus.ACTIVE})
        importance_sum = sum(memory.importance for memory in candidates)
        if not force and importance_sum < self.config.reflect_importance_threshold:
            return {
                "n_facts": 0,
                "n_insights": 0,
                "promoted_l4": [],
                "processed": 0,
                "failed": 0,
                "inbox_remaining": self.inbox.pending_count(scope_id),
                "storage_path": self._storage_path_after_write(scope_id),
            }
        if force or self.inbox.pending_count(scope_id) == 0:
            for memory in candidates:
                self._enqueue_consolidation(memory)
        batch_size = self.config.consolidation_batch_size
        if force:
            batch_size = max(batch_size, self.inbox.pending_count(scope_id))
        result = self.consolidation_agent.run_once(
            scope_id,
            batch_size=batch_size,
        )
        result["graph_audit"] = self.l4.audit(scope_id, repair=False)
        result["storage_path"] = self._storage_path_after_write(scope_id)
        return result

    def forget_sweep(self, scope_id: str = "default") -> Dict[str, Any]:
        """Run asynchronous evolution cleanup.

        输入:
            scope_id: 作用域 ID。
        输出:
            dict: L2 遗忘、L3 淘汰与 L4 剪枝结果。
        示例:
            示例输入: memory.forget_sweep("scope")
            示例输出: {"checked": 10.0, "archived": 1.0, "l3_removed": 0, ...}
        """
        l2_result = self.l2.decay_sweep(scope_id)
        affected_evidence_ids = list(l2_result.get("archived_ids", [])) + list(
            l2_result.get("deleted_ids", [])
        )
        l3_degraded = self.l3.degrade_orphaned_evidence(
            scope_id, affected_evidence_ids
        )
        l3_removed = self.l3.prune_low_confidence(scope_id)
        l4_pruned = self.l4.prune(scope_id)
        graph_audit = self.l4.audit(scope_id)
        result: Dict[str, Any] = dict(l2_result)
        result["l3_degraded"] = l3_degraded
        result["l3_removed"] = l3_removed
        result["l4_pruned"] = l4_pruned
        result["graph_audit"] = graph_audit
        self.persistence.mark_dirty(scope_id)
        result["storage_path"] = self._storage_path_after_write(scope_id)
        return result

    def memorize(
        self,
        session_id: str,
        text: str,
        scope_id: str = "default",
        importance: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Explicitly memorize text.

        输入:
            session_id: 会话 ID。
            text: 记忆正文。
            scope_id: 作用域 ID。
            importance: 可选显式重要性。
        输出:
            dict: mem_id、importance。
        示例:
            示例输入: memory.memorize("s1", "记住 user.lang=zh")
            示例输出: {"mem_id": "...", "importance": 8}
        """
        now_ts = time.time()
        identity = MemoryIdentity.from_parts(session_id, scope_id)
        memory = self._promote_text(
            text=text,
            scope_id=scope_id,
            source_ids=[identity.source_prefix()],
            user_text=text,
            ts=now_ts,
            importance=importance,
        )
        return {
            "mem_id": memory.mem_id,
            "importance": memory.importance,
            "inbox_pending": self.inbox.pending_count(scope_id),
            "storage_path": self._storage_path_after_write(scope_id),
        }

    def search(
        self,
        session_id: str,
        query: str,
        scope_id: str = "default",
        k: int = 8,
    ) -> Dict[str, Any]:
        """Search memory through the recall pipeline.

        输入:
            session_id: 会话 ID。
            query: 查询文本。
            scope_id: 作用域 ID。
            k: 返回数量。
        输出:
            dict: recall 结果。
        示例:
            示例输入: memory.search("s1", "Agent")
            示例输出: {"facts": [...], "episodes": [...], "subgraph": {...}, ...}
        """
        return self.recall(
            session_id,
            query,
            k=min(k, self.config.max_recall_k),
            scope_id=scope_id,
            include_archived=False,
        )

    def forget(
        self,
        scope_id: str = "default",
        mode: str = "decay",
        mem_id: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Run explicit forget modes.

        输入:
            scope_id: 作用域 ID。
            mode: decay、hard 或 expire。
            mem_id: hard 模式的目标记忆 ID。
            force: 是否允许删除 importance>=9 的保护记忆。
        输出:
            dict: 操作结果。
        示例:
            示例输入: memory.forget(mode="hard", mem_id="m1", force=True)
            示例输出: {"deleted": 1, "mem_id": "m1"}
        """
        if mode == FORGET_MODE_DECAY:
            return self.forget_sweep(scope_id)
        if mode == FORGET_MODE_HARD:
            result = self._hard_forget(scope_id, mem_id, force)
            self.persistence.mark_dirty(scope_id)
            result["storage_path"] = self._storage_path_after_write(scope_id)
            return result
        if mode == FORGET_MODE_EXPIRE:
            result = self._expire_archived(scope_id)
            self.persistence.mark_dirty(scope_id)
            result["storage_path"] = self._storage_path_after_write(scope_id)
            return result
        msg = "mode must be one of decay, hard, expire."
        raise ValueError(msg)

    def graph_audit(
        self,
        scope_id: str = "default",
        repair: bool = True,
    ) -> Dict[str, int]:
        """Run the L4 graph audit job.

        输入:
            scope_id: 作用域 ID。
            repair: 是否修复孤儿边。
        输出:
            dict: 图谱巡检统计。
        示例:
            示例输入: memory.graph_audit("scope", repair=True)
            示例输出: {"checked_nodes": 3, "orphan_edges": 0, ...}
        """
        return self.l4.audit(scope_id, repair)

    def backend_diagnostics(self) -> Dict[str, Any]:
        """Return Port/Adapter backend diagnostics.

        输入:
            self: AgentMemory 实例。
        输出:
            dict: 当前后端 profile、各层 Adapter 类型与外部服务摘要。
        示例:
            示例输入: memory.backend_diagnostics()
            示例输出: {"profile": "memory", "adapters": {...}}
        """
        return self.backend.diagnostics()

    def architecture_snapshot(self, scope_id: str = "default") -> Dict[str, Any]:
        """Return a cross-layer operational snapshot.

        输入:
            scope_id: 作用域 ID。
        输出:
            dict: L0-L4 的容量、会话、检索诊断与图谱统计。
        示例:
            示例输入: memory.architecture_snapshot("scope")
            示例输出: {"scope_id": "scope", "l2": {"active": 1, ...}, ...}
        """
        l2_records = self.l2.all_records(scope_id)
        return {
            "scope_id": scope_id,
            "l0_sessions": [
                identity.to_dict() for identity in self.l0.active_sessions(scope_id)
            ],
            "l1_sessions": [
                identity.to_dict() for identity in self.l1.active_sessions(scope_id)
            ],
            "l2": {
                "active": sum(
                    1 for record in l2_records if record.status == MemoryStatus.ACTIVE
                ),
                "archived": sum(
                    1 for record in l2_records if record.status == MemoryStatus.ARCHIVED
                ),
                "deleted": sum(
                    1 for record in l2_records if record.status == MemoryStatus.DELETED
                ),
                "occupancy": self.l2.occupancy(scope_id),
                "last_retrieval": self.l2.last_retrieval_stats(),
            },
            "l3": {
                "facts": len(self.l3.all_facts(scope_id)),
                "conflicts": len(self.l3.conflict_log(scope_id)),
            },
            "l4": {
                "nodes": len(self.l4.all_nodes(scope_id)),
                "edges": len(self.l4.all_edges(scope_id)),
                "audit": self.l4.audit(scope_id, repair=False),
            },
            "inbox": self.inbox.stats(scope_id),
            "persistence": self.persistence.stats(scope_id),
            "backend": self.backend.diagnostics(),
        }

    def update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update an L2 memory or L3 fact.

        输入:
            payload: L2 使用 mem_id；L3 使用 fact_key。
        输出:
            dict: 更新结果。
        示例:
            示例输入: memory.update({"fact_key": "user.lang", "value": "en"})
            示例输出: {"fact_key": "user.lang", "version": 2, "action": "replaced"}
        """
        scope_id = str(payload.get("scope_id", "default"))
        if "fact_key" in payload:
            return self.upsert_fact(payload)
        if "mem_id" in payload:
            record = self.l2.update(
                mem_id=str(payload["mem_id"]),
                scope_id=scope_id,
                text=payload.get("text"),
                importance=payload.get("importance"),
            )
            return {
                "mem_id": record.mem_id,
                "action": "updated",
                "storage_path": self._storage_path_after_write(scope_id),
            }
        msg = "payload must include fact_key or mem_id."
        raise ValueError(msg)

    def storage_path(self, scope_id: str = "default") -> str:
        """Return the project-relative storage path for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            str: `.memories` 下的项目相对 JSON 文件路径。
        示例:
            示例输入: memory.storage_path("scope")
            示例输出: ".memories/scopes/scope/memory-state.json"
        """
        return self.storage.scope_state_relative_path(scope_id)

    def read_stored_state(
        self,
        scope_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """Read persisted Memory state for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            dict | None: `.memories` 中的状态快照；不存在时返回 None。
        示例:
            示例输入: memory.read_stored_state("scope")
            示例输出: {"scope_id": "scope", "l2": [...], ...} 或 None。
        """
        return self.storage.read_scope_state(scope_id)

    def flush(self, scope_id: str = "default") -> str:
        """Persist one scope snapshot through the PersistenceManager.

        输入:
            scope_id: 作用域 ID。
        输出:
            str: `.memories` 下的项目相对 JSON 文件路径。
        示例:
            示例输入: memory.flush("scope")
            示例输出: ".memories/scopes/scope/memory-state.json"
        """
        return self._persist_scope(scope_id)

    def _storage_path_after_write(self, scope_id: str) -> str:
        """Return the storage path after a write-side mutation.

        输入:
            scope_id: 作用域 ID。
        输出:
            str: 快照路径；persist_on_write=True 时已同步写入。
        示例:
            示例输入: memory._storage_path_after_write("scope")
            示例输出: ".memories/scopes/scope/memory-state.json"
        """
        self.persistence.mark_dirty(scope_id)
        if self.config.persist_on_write:
            return self.flush(scope_id)
        return self.storage_path(scope_id)

    def _persist_scope(self, scope_id: str) -> str:
        """Persist the current scope state into `.memories`.

        输入:
            scope_id: 作用域 ID。
        输出:
            str: 写入文件的项目相对路径。
        示例:
            示例输入: memory._persist_scope("scope")
            示例输出: ".memories/scopes/scope/memory-state.json"
        """
        return self.persistence.flush_scope(scope_id, self._scope_state(scope_id))

    def _scope_state(self, scope_id: str) -> Dict[str, Any]:
        """Build a JSON-compatible scope state snapshot.

        输入:
            scope_id: 作用域 ID。
        输出:
            dict: L0-L4 和架构诊断的可序列化状态。
        示例:
            示例输入: memory._scope_state("scope")
            示例输出: {"scope_id": "scope", "l0": {...}, "l2": [...], ...}
        """
        l1_states = []
        for identity in self.l1.active_sessions(scope_id):
            active = self.l1.get_active_context(
                identity.session_id,
                identity.scope_id,
            )
            l1_states.append(
                {
                    "session_id": active.session_id,
                    "scope_id": active.scope_id,
                    "rolling_summary": active.rolling_summary,
                    "open_slots": list(active.open_slots),
                    "mentioned_entities": list(active.mentioned_entities),
                    "token_used": active.token_used,
                    "last_compress_ts": active.last_compress_ts,
                }
            )
        return {
            "scope_id": scope_id,
            "memory_dir": self.config.memory_dir,
            "l0": self.l0.snapshot(scope_id),
            "l1": l1_states,
            "l2": [record.to_dict() for record in self.l2.all_records(scope_id)],
            "l3": {
                "facts": [fact.to_dict() for fact in self.l3.all_facts(scope_id)],
                "conflicts": self.l3.conflict_log(scope_id),
            },
            "l4": {
                "nodes": [node.to_dict() for node in self.l4.all_nodes(scope_id)],
                "edges": [edge.to_dict() for edge in self.l4.all_edges(scope_id)],
                # 失效证据集合必须随快照落盘：status 由它推导，
                # 丢了它重启后 SUPERSEDED 洞察会被误判为有效。
                "stale_evidence": sorted(self.l4.stale_evidence_ids(scope_id)),
            },
            "inbox": self.inbox.snapshot(scope_id),
            "persistence": self.persistence.stats(scope_id),
            "architecture": self.architecture_snapshot(scope_id),
        }

    def _compress_and_promote(self, session_id: str, scope_id: str) -> List[str]:
        """Compress L0 into L1 and promote closed slots.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            list[str]: 新 promoted mem_id。
        示例:
            示例输入: memory._compress_and_promote("s1", "scope")
            示例输出: ["mem-id-1", "mem-id-2"]
        """
        messages = self.l0.flush_to_l1(session_id, scope_id)
        self.l1.compress(session_id, messages, scope_id=scope_id)
        return self._promote_l1_closed_slots(session_id, scope_id)

    def _promote_l1_closed_slots(self, session_id: str, scope_id: str) -> List[str]:
        """Promote currently closed L1 slots into L2.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            list[str]: promoted mem_id 列表。
        示例:
            示例输入: memory._promote_l1_closed_slots("s1", "scope")
            示例输出: ["mem-id-1"]
        """
        closed_slots = self.l1.promote(session_id, scope_id)
        promoted = []
        for slot in closed_slots:
            stored = self._promote_text(
                text=str(slot["text"]),
                scope_id=scope_id,
                source_ids=list(slot.get("source_ids", [])),
                user_text=str(slot["text"]),
                ts=float(slot.get("ts", time.time())),
            )
            promoted.append(stored.mem_id)
        return promoted

    def _promote_text(
        self,
        text: str,
        scope_id: str,
        source_ids: List[str],
        user_text: str,
        ts: float,
        importance: Optional[int] = None,
    ) -> EpisodicMemory:
        """Write a text memory into L2.

        输入:
            text: 记忆正文。
            scope_id: 作用域 ID。
            source_ids: 来源 ID。
            user_text: 用户原文，用于 F1。
            ts: 时间戳。
            importance: 可选重要性覆盖。
        输出:
            EpisodicMemory: L2 记录。
        示例:
            示例输入: memory._promote_text("记住 x", "scope", [], "记住 x", 1.0)
            示例输出: EpisodicMemory(text="记住 x", scope_id="scope", ...)
        """
        if importance is None:
            importance = self._importance_for_text(user_text)
        mem_type = self._infer_memory_type(text)
        memory = self.l2.promote(
            text=text,
            scope_id=scope_id,
            importance=importance,
            source_ids=source_ids,
            ts=ts,
            mem_type=mem_type,
        )
        self._enqueue_consolidation(memory)
        self.persistence.mark_dirty(scope_id)
        return memory

    def _importance_for_text(self, text: str) -> int:
        """Compute F1 importance from local signals.

        输入:
            text: 用户文本。
        输出:
            int: importance。
        示例:
            示例输入: memory._importance_for_text("请记住")
            示例输出: 6
        """
        rule = rule_signal_score(text)
        user = user_emphasis_score(text)
        llm_proxy = min(10, max(1, (rule + user) / 2 + len(text) / 200))
        return f1_importance(llm_proxy, rule, user)

    def _validate_k(self, k: int) -> None:
        """Validate recall size.

        输入:
            k: 请求返回数量。
        输出:
            None；非法时抛出 ValueError。
        示例:
            示例输入: memory._validate_k(8)
            示例输出: None
        """
        validate_recall_k(k, self.config.max_recall_k)

    def _is_explicit_memory(self, text: str) -> bool:
        """Check whether text carries explicit memorize intent.

        输入:
            text: 用户文本。
        输出:
            bool: 是否包含记忆指令。
        示例:
            示例输入: memory._is_explicit_memory("请记住")
            示例输出: True
        """
        return is_explicit_memory(text)

    def _fact_specs_from_memory(self, memory: EpisodicMemory) -> List[Dict[str, Any]]:
        """Extract deterministic fact candidates from an L2 memory.

        输入:
            memory: L2 记忆对象。
        输出:
            list[dict]: 可传给 L3 upsert 的事实规格。
        示例:
            示例输入: memory_service._fact_specs_from_memory(memory)
            示例输出: [{"fact_key": "user.lang_pref", "value": "zh", ...}]
        """
        text = memory.text
        facts: List[Dict[str, Any]] = []
        for match in KEY_VALUE_MEMORY.finditer(text):
            fact_key = match.group(1)
            mem_type = self._infer_fact_memory_type(fact_key, text)
            facts.append(
                {
                    "fact_key": fact_key,
                    "value": match.group(2).strip(),
                    "confidence": min(1.0, 0.6 + memory.importance / 20),
                    "evidence_ids": [memory.mem_id],
                    "mem_type": mem_type,
                    "partition": self._partition_for_memory_type(mem_type),
                }
            )
        if "语言" in text and ("中文" in text or "zh" in text.lower()):
            facts.append(
                {
                    "fact_key": "user.lang_pref",
                    "value": "zh",
                    "confidence": min(1.0, 0.65 + memory.importance / 20),
                    "evidence_ids": [memory.mem_id],
                    "mem_type": MemoryType.PREFERENCE,
                    "partition": PARTITION_PREFERENCE,
                }
            )
        if "偏好" in text or "喜欢" in text:
            facts.append(
                {
                    "fact_key": "user.preference." + self._short_hash(text),
                    "value": text,
                    "confidence": min(1.0, 0.55 + memory.importance / 20),
                    "evidence_ids": [memory.mem_id],
                    "mem_type": MemoryType.PREFERENCE,
                    "partition": PARTITION_PREFERENCE,
                }
            )
        if self._is_explicit_memory(text) and not facts:
            facts.append(
                {
                    "fact_key": "memory.explicit." + self._short_hash(text),
                    "value": text,
                    "confidence": min(1.0, 0.55 + memory.importance / 20),
                    "evidence_ids": [memory.mem_id],
                    "mem_type": memory.mem_type,
                    "partition": self._partition_for_memory_type(memory.mem_type),
                }
            )
        return facts

    def _enqueue_consolidation(self, memory: EpisodicMemory) -> str:
        """Enqueue an L2 memory for asynchronous consolidation.

        输入:
            memory: L2 情景记忆对象。
        输出:
            str: inbox 条目 ID。
        示例:
            示例输入: memory_service._enqueue_consolidation(memory)
            示例输出: "ci_..."。
        """
        item = self.inbox.enqueue(memory, mem_type_hint=memory.mem_type)
        return item.item_id

    def _infer_memory_type(self, text: str) -> MemoryType:
        """Infer a logical memory type from raw text.

        输入:
            text: 记忆文本。
        输出:
            MemoryType: preference、procedural 或 episodic。
        示例:
            示例输入: memory._infer_memory_type("记住 user.preference.food=清淡")
            示例输出: MemoryType.PREFERENCE
        """
        lowered = text.lower()
        if "preference." in lowered or "偏好" in text or "喜欢" in text:
            return MemoryType.PREFERENCE
        if "procedure." in lowered or "workflow." in lowered or "流程" in text:
            return MemoryType.PROCEDURAL
        return MemoryType.EPISODIC

    def _infer_fact_memory_type(self, fact_key: str, text: str) -> MemoryType:
        """Infer the L3 memory type for a fact candidate.

        输入:
            fact_key: 候选事实键。
            text: 来源文本。
        输出:
            MemoryType: semantic、preference 或 procedural。
        示例:
            示例输入: memory._infer_fact_memory_type("user.lang_pref", "语言偏好")
            示例输出: MemoryType.PREFERENCE
        """
        key = fact_key.lower()
        if ".preference." in key or key.endswith("_pref"):
            return MemoryType.PREFERENCE
        if key.startswith("procedure.") or key.startswith("workflow."):
            return MemoryType.PROCEDURAL
        if "偏好" in text or "喜欢" in text:
            return MemoryType.PREFERENCE
        return MemoryType.SEMANTIC

    def _partition_for_memory_type(self, mem_type: MemoryType) -> str:
        """Return the L3 partition for a memory type.

        输入:
            mem_type: 逻辑记忆类型。
        输出:
            str: L3 分区名。
        示例:
            示例输入: memory._partition_for_memory_type(MemoryType.PREFERENCE)
            示例输出: "preference"
        """
        if mem_type == MemoryType.PREFERENCE:
            return PARTITION_PREFERENCE
        if mem_type == MemoryType.PROCEDURAL:
            return PARTITION_PROCEDURAL
        return PARTITION_SEMANTIC

    def _memory_type_from_value(self, value: object) -> MemoryType:
        """Normalize external memory type values.

        输入:
            value: MemoryType 或字符串。
        输出:
            MemoryType: 标准枚举值。
        示例:
            示例输入: memory._memory_type_from_value("preference")
            示例输出: MemoryType.PREFERENCE
        """
        if isinstance(value, MemoryType):
            return value
        return MemoryType(str(value))

    def _entities_from_text(self, text: str) -> List[str]:
        """Extract entity labels for L4 graph consolidation.

        输入:
            text: 记忆文本。
        输出:
            list[str]: 实体标签。
        示例:
            示例输入: memory._entities_from_text("Agent 记忆系统")
            示例输出: ["agent", "记忆系统"]
        """
        return extract_entities(text)

    def _insight_label(self, text: str) -> str:
        """Create a concise L4 insight label.

        输入:
            text: 记忆文本。
        输出:
            str: 洞察标签。
        示例:
            示例输入: memory._insight_label("long text")
            示例输出: "long text"
        """
        return insight_label(text)

    def _short_hash(self, text: str) -> str:
        """Create a stable short hash.

        输入:
            text: 原始文本。
        输出:
            str: 8 位哈希。
        示例:
            示例输入: memory._short_hash("abc")
            示例输出: "cf4ab791"
        """
        return short_hash(text)

    def _hard_forget(
        self, scope_id: str, mem_id: Optional[str], force: bool
    ) -> Dict[str, Any]:
        """Hard-delete a specific L2 memory.

        输入:
            scope_id: 作用域 ID。
            mem_id: 目标记忆 ID。
            force: 是否跳过保护检查。
        输出:
            dict: 删除结果。
        示例:
            示例输入: memory._hard_forget("scope", "m1", True)
            示例输出: {"deleted": 1, "mem_id": "m1"}
        """
        if not mem_id:
            msg = "mem_id is required for hard forget."
            raise ValueError(msg)
        record = self.l2.get(mem_id, scope_id)
        if record is None:
            return {"deleted": 0, "reason": "not_found"}
        if record.importance >= 9 and not force:
            msg = "importance>=9 memory requires force=True."
            raise ProtectedMemoryError(msg)
        record.status = MemoryStatus.DELETED
        return {"deleted": 1, "mem_id": mem_id}

    def _cascade_stale_evidence(self, scope_id: str, evidence_ids: List[str]) -> int:
        """Mark L4 insights stale after L3 fact replacement or archival.

        输入:
            scope_id: 作用域 ID。
            evidence_ids: 被替换事实的旧证据 ID。
        输出:
            int: 被标记为 superseded 的 L4 节点数。
        示例:
            示例输入: memory._cascade_stale_evidence("scope", ["m1"])
            示例输出: 1
        """
        return self.l4.mark_evidence_stale(scope_id, evidence_ids)

    def _expire_archived(self, scope_id: str) -> Dict[str, Any]:
        """Delete archived L2 memories.

        输入:
            scope_id: 作用域 ID。
        输出:
            dict: 删除数量。
        示例:
            示例输入: memory._expire_archived("scope")
            示例输出: {"deleted": 2}
        """
        deleted = 0
        for record in self.l2.all_records(scope_id, {MemoryStatus.ARCHIVED}):
            record.status = MemoryStatus.DELETED
            deleted += 1
        return {"deleted": deleted}


__all__ = ["AgentMemory"]
