"""Recall agent for layered memory retrieval."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from ..config.settings import MemoryConfig
from ..graph.cognitive import CognitiveGraph
from ..memory.episodic import EpisodicStore
from ..memory.models import EpisodicMemory, RecallPlan, RecallResult
from ..memory.semantic import SemanticStore

DirtyMarker = Callable[[str], None]


class RecallAgent:
    """Online recall orchestrator with a bounded zero-LLM critical path."""

    def __init__(
        self,
        config: MemoryConfig,
        l2: EpisodicStore,
        l3: SemanticStore,
        l4: CognitiveGraph,
        mark_dirty: Optional[DirtyMarker] = None,
    ) -> None:
        """Initialize the recall agent.

        输入:
            config: 系统配置。
            l2: L2 情景记忆库。
            l3: L3 语义事实库。
            l4: L4 认知图谱。
            mark_dirty: 可选 dirty 标记回调。
        输出:
            None。
        示例:
            示例输入: RecallAgent(config, l2, l3, l4)
            示例输出: RecallAgent 实例可执行 recall。
        """
        self.config = config
        self.l2 = l2
        self.l3 = l3
        self.l4 = l4
        self.mark_dirty = mark_dirty

    def plan_routes(
        self,
        scope_id: str,
        query: str,
        k: int,
        entities: Optional[List[str]] = None,
    ) -> RecallPlan:
        """Build a deterministic layered recall plan.

        输入:
            scope_id: 作用域 ID。
            query: 查询文本。
            k: 返回数量。
            entities: 可选实体标签。
        输出:
            RecallPlan: 分层路由计划。
        示例:
            示例输入: agent.plan_routes("scope", "偏好", 3)
            示例输出: RecallPlan(routes=["preference", "l3", "l2", "l4"], ...)
        """
        routes = ["preference", "l3", "l2"]
        include_graph = bool(query or entities)
        if include_graph:
            routes.append("l4")
        return RecallPlan(
            scope_id=scope_id,
            query=query,
            k=k,
            routes=routes,
            include_preferences=True,
            include_graph=include_graph,
        )

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
            include_archived: 是否允许 archived 记忆召回。
        输出:
            dict: facts、episodes、subgraph、reinforced 与 plan。
        示例:
            示例输入: agent.recall("s1", "语言偏好", k=3, scope_id="t1")
            示例输出: {"facts": [...], "episodes": [...], "plan": {...}, ...}
        """
        plan = self.plan_routes(scope_id, query, k, entities)
        episodes = self.l2.retrieve(
            query=query,
            scope_id=scope_id,
            k=k,
            include_archived=include_archived,
        )
        reinforced = self._reinforce(scope_id, episodes)
        facts = self._recall_facts(query, scope_id, k, plan)
        if plan.include_graph and entities:
            subgraph = self.l4.subgraph_for_context(scope_id, entities, k)
        elif plan.include_graph:
            subgraph = self.l4.graph_query(scope_id, query, k)
        else:
            subgraph = {"nodes": [], "edges": []}
        return RecallResult(
            facts=facts,
            episodes=episodes,
            subgraph=subgraph,
            reinforced=reinforced,
            plan=plan,
        ).to_dict()

    def _recall_facts(
        self,
        query: str,
        scope_id: str,
        k: int,
        plan: RecallPlan,
    ) -> List[Any]:
        """Recall L3 facts with preference partition priority.

        输入:
            query: 查询文本。
            scope_id: 作用域 ID。
            k: 返回数量。
            plan: RecallPlan 路由计划。
        输出:
            list[SemanticFact]: preference 优先的事实列表。
        示例:
            示例输入: agent._recall_facts("偏好", "scope", 3, plan)
            示例输出: [SemanticFact(...)]
        """
        facts = []
        seen = set()
        if plan.include_preferences:
            for fact in self.l3.query_relevant(
                "",
                scope_id,
                min(k, self.config.max_recall_k),
                partition="preference",
            ):
                facts.append(fact)
                seen.add(fact.fact_key)
        for fact in self.l3.query_relevant(query, scope_id, k):
            if fact.fact_key not in seen:
                facts.append(fact)
                seen.add(fact.fact_key)
        return facts[:k]

    def _reinforce(
        self,
        scope_id: str,
        episodes: List[EpisodicMemory],
    ) -> List[str]:
        """Reinforce recalled L2 episodes without synchronous persistence.

        输入:
            scope_id: 作用域 ID。
            episodes: 本次召回命中的情景记忆。
        输出:
            list[str]: 被成功强化的 mem_id 列表。
        示例:
            示例输入: agent._reinforce("scope", [memory])
            示例输出: ["m1"]
        """
        reinforced = []
        now_ts = time.time()
        for episode in episodes:
            updated = self.l2.reinforce(episode.mem_id, scope_id, now_ts)
            if updated is not None:
                reinforced.append(episode.mem_id)
        if reinforced and self.mark_dirty is not None:
            self.mark_dirty(scope_id)
        return reinforced
