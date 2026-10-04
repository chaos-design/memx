"""Consolidation agent for asynchronous memory evolution."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ..config.settings import MemoryConfig
from ..graph.cognitive import CognitiveGraph
from ..ingest.inbox import InMemoryInbox
from ..memory.episodic import EpisodicStore
from ..memory.models import (
    ConsolidationInboxItem,
    EpisodicMemory,
    MemoryStatus,
    MemoryType,
)
from ..memory.semantic import SemanticStore

FactExtractor = Callable[[EpisodicMemory], List[Dict[str, Any]]]
TextExtractor = Callable[[str], List[str]]
LabelExtractor = Callable[[str], str]
DirtyMarker = Callable[[str], None]
StaleEvidenceMarker = Callable[[str, List[str]], int]


class ConsolidationAgent:
    """Asynchronous consolidation worker consuming inbox candidates."""

    def __init__(
        self,
        config: MemoryConfig,
        inbox: InMemoryInbox,
        l2: EpisodicStore,
        l3: SemanticStore,
        l4: CognitiveGraph,
        fact_extractor: FactExtractor,
        entity_extractor: TextExtractor,
        insight_labeler: LabelExtractor,
        mark_stale_evidence: StaleEvidenceMarker,
        mark_dirty: Optional[DirtyMarker] = None,
    ) -> None:
        """Initialize the consolidation agent.

        输入:
            config: 系统配置。
            inbox: 待固化队列。
            l2: L2 情景记忆库。
            l3: L3 语义事实库。
            l4: L4 认知图谱。
            fact_extractor: L2 到 L3 候选事实抽取函数。
            entity_extractor: L4 实体抽取函数。
            insight_labeler: L4 洞察标签生成函数。
            mark_stale_evidence: 旧证据失效回调。
            mark_dirty: 可选 dirty 标记回调。
        输出:
            None。
        示例:
            示例输入: ConsolidationAgent(config, inbox, l2, l3, l4, f, e, label, stale)
            示例输出: ConsolidationAgent 实例可执行 run_once。
        """
        self.config = config
        self.inbox = inbox
        self.l2 = l2
        self.l3 = l3
        self.l4 = l4
        self.fact_extractor = fact_extractor
        self.entity_extractor = entity_extractor
        self.insight_labeler = insight_labeler
        self.mark_stale_evidence = mark_stale_evidence
        self.mark_dirty = mark_dirty

    def run_once(self, scope_id: str, batch_size: int = 50) -> Dict[str, Any]:
        """Process one bounded consolidation batch.

        输入:
            scope_id: 作用域 ID。
            batch_size: 最大处理条目数。
        输出:
            dict: 处理数量、事实数、洞察数、失败数和 inbox 剩余量。
        示例:
            示例输入: agent.run_once("scope", batch_size=10)
            示例输出: {"processed": 1, "n_facts": 1, "n_insights": 0, ...}
        """
        items = self.inbox.pull(scope_id, batch_size)
        processed = 0
        failed = 0
        n_facts = 0
        promoted_l4 = []
        for item in items:
            try:
                result = self.consolidate(item)
            except Exception as exc:
                self.inbox.mark_failed(scope_id, item.item_id, str(exc))
                failed += 1
                continue
            processed += 1
            n_facts += int(result["n_facts"])
            promoted_l4.extend(result["promoted_l4"])
        if processed and self.mark_dirty is not None:
            self.mark_dirty(scope_id)
        return {
            "processed": processed,
            "failed": failed,
            "n_facts": n_facts,
            "n_insights": len(promoted_l4),
            "promoted_l4": promoted_l4,
            "inbox_remaining": self.inbox.pending_count(scope_id),
        }

    def consolidate(self, item: ConsolidationInboxItem) -> Dict[str, Any]:
        """Consolidate one inbox item into L3/L4.

        输入:
            item: 待固化 inbox 条目。
        输出:
            dict: 单条固化结果。
        示例:
            示例输入: agent.consolidate(item)
            示例输出: {"n_facts": 1, "promoted_l4": ["node-id"]}
        """
        memory = self.l2.get(item.mem_id, item.scope_id)
        if memory is None or memory.status == MemoryStatus.DELETED:
            msg = "source memory not found or deleted."
            raise KeyError(msg)
        n_facts = self._write_facts(item.scope_id, memory)
        promoted_l4 = self._write_insight(item.scope_id, memory)
        self.inbox.mark_done(item.scope_id, item.item_id)
        return {"n_facts": n_facts, "promoted_l4": promoted_l4}

    def _write_facts(self, scope_id: str, memory: EpisodicMemory) -> int:
        """Write extracted facts through the L3 conflict gate.

        输入:
            scope_id: 作用域 ID。
            memory: L2 情景记忆对象。
        输出:
            int: 成功创建、更新、合并或归档的事实数量。
        示例:
            示例输入: agent._write_facts("scope", memory)
            示例输出: 1
        """
        n_facts = 0
        for fact in self.fact_extractor(memory):
            result = self.l3.upsert(scope_id=scope_id, **fact)
            self.mark_stale_evidence(
                scope_id,
                result.get("superseded_evidence_ids", []),
            )
            if result["action"] in {"created", "replaced", "archived", "merged"}:
                n_facts += 1
        return n_facts

    def _write_insight(self, scope_id: str, memory: EpisodicMemory) -> List[str]:
        """Promote high-value episodic evidence into the L4 graph.

        输入:
            scope_id: 作用域 ID。
            memory: L2 情景记忆对象。
        输出:
            list[str]: 新增或更新的 L4 节点 ID。
        示例:
            示例输入: agent._write_insight("scope", memory)
            示例输出: ["node-id"] 或 []。
        """
        if memory.importance < 6 and memory.access_count <= 1:
            return []
        entities = self.entity_extractor(memory.text)
        node = self.l4.add_insight(
            scope_id=scope_id,
            label=self.insight_labeler(memory.text),
            evidence_ids=[memory.mem_id],
            entities=entities[:5],
            salience=min(1.0, 0.3 + memory.importance / 10.0),
            mem_type=self._graph_mem_type(memory),
        )
        return [node.node_id]

    def _graph_mem_type(self, memory: EpisodicMemory) -> MemoryType:
        """Infer L4 node memory type from its source memory.

        输入:
            memory: L2 情景记忆对象。
        输出:
            MemoryType: procedural 或 semantic。
        示例:
            示例输入: agent._graph_mem_type(memory)
            示例输出: MemoryType.SEMANTIC
        """
        if memory.mem_type == MemoryType.PROCEDURAL:
            return MemoryType.PROCEDURAL
        return MemoryType.SEMANTIC
