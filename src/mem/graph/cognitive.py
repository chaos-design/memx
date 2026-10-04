"""L4 cognitive graph memory."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import DefaultDict, Dict, List, Optional, Set

from ..config.settings import MemoryConfig
from ..embedding.scoring import salience_update
from ..memory.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    InsightStatus,
    MemoryType,
    NodeType,
)


class CognitiveGraph:
    """In-memory knowledge graph for entities, concepts, and insights."""

    def __init__(self, config: MemoryConfig) -> None:
        """Initialize the graph.

        输入:
            config: 系统配置。
        输出:
            None。
        示例:
            示例输入: CognitiveGraph(MemoryConfig())
            示例输出: CognitiveGraph 实例，节点与边为空。
        """
        self.config = config

        # 图节点主存储：scope_id -> node_id -> GraphNode。
        self._nodes: DefaultDict[str, Dict[str, GraphNode]] = defaultdict(dict)

        # 图边存储：scope_id -> GraphEdge 列表。
        self._edges: DefaultDict[str, List[GraphEdge]] = defaultdict(list)

        # label 去重索引：scope_id -> "type:normalized_label" -> node_id。
        self._label_index: DefaultDict[str, Dict[str, str]] = defaultdict(dict)

    def add_insight(
        self,
        scope_id: str,
        label: str,
        evidence_ids: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        salience: float = 0.5,
        mem_type: MemoryType = MemoryType.SEMANTIC,
    ) -> GraphNode:
        """Add or update an insight node and connect related entities.

        输入:
            scope_id: 作用域 ID。
            label: 洞察标签。
            evidence_ids: 证据 ID。
            entities: 相关实体。
            salience: 初始显著度。
            mem_type: 逻辑记忆类型。
        输出:
            GraphNode: 洞察节点。
        示例:
            示例输入: graph.add_insight("scope", "memory pipeline", entities=["Agent"])
            示例输出:
                GraphNode(node_type=NodeType.INSIGHT, label="memory pipeline", ...)
        """
        node = self._upsert_node(
            scope_id=scope_id,
            label=label,
            node_type=NodeType.INSIGHT,
            evidence_ids=evidence_ids or [],
            salience=salience,
            mem_type=mem_type,
        )
        for entity in entities or []:
            entity_node = self._upsert_node(
                scope_id=scope_id,
                label=entity,
                node_type=NodeType.ENTITY,
                evidence_ids=evidence_ids or [],
                salience=max(0.3, salience * 0.8),
                mem_type=mem_type,
            )
            self._upsert_edge(
                scope_id=scope_id,
                source_id=node.node_id,
                target_id=entity_node.node_id,
                edge_type=EdgeType.BELONG,
                weight=0.7,
            )
        return node

    def graph_query(
        self, scope_id: str, query: str, k: int = 8
    ) -> Dict[str, List[dict]]:
        """Query graph nodes by label.

        输入:
            scope_id: 作用域 ID。
            query: 查询文本。
            k: 节点数量上限。
        输出:
            dict: nodes 与 edges。
        示例:
            示例输入: graph.graph_query("scope", "memory")
            示例输出: {"nodes": [...], "edges": [...]}
        """
        terms = [term.lower() for term in query.split() if term]
        nodes = [
            node
            for node in self._nodes.get(scope_id, {}).values()
            if not terms or any(term in node.label.lower() for term in terms)
        ]
        nodes = sorted(nodes, key=lambda node: node.salience, reverse=True)[:k]
        node_ids = {node.node_id for node in nodes}
        edges = [
            edge
            for edge in self._edges.get(scope_id, [])
            if edge.source_id in node_ids or edge.target_id in node_ids
        ]
        return self._serialize(nodes, edges)

    def subgraph_for_context(
        self, scope_id: str, entities: Optional[List[str]], k: int = 8
    ) -> Dict[str, List[dict]]:
        """Return a context subgraph for known entities.

        输入:
            scope_id: 作用域 ID。
            entities: 实体标签列表。
            k: 节点数量上限。
        输出:
            dict: nodes 与 edges。
        示例:
            示例输入: graph.subgraph_for_context("scope", ["Agent"])
            示例输出: {"nodes": [...], "edges": [...]}
        """
        if not entities:
            return self.graph_query(scope_id, "", k)
        entity_terms = {entity.lower() for entity in entities}
        nodes = [
            node
            for node in self._nodes.get(scope_id, {}).values()
            if node.label.lower() in entity_terms
        ]
        node_ids = {node.node_id for node in nodes}
        edges = [
            edge
            for edge in self._edges.get(scope_id, [])
            if edge.source_id in node_ids or edge.target_id in node_ids
        ]
        connected_ids = set(node_ids)
        for edge in edges:
            connected_ids.add(edge.source_id)
            connected_ids.add(edge.target_id)
        connected = [
            node
            for node in self._nodes.get(scope_id, {}).values()
            if node.node_id in connected_ids
        ]
        connected = sorted(connected, key=lambda node: node.salience, reverse=True)[:k]
        return self._serialize(connected, edges)

    def prune(self, scope_id: str) -> int:
        """Decay salience and remove low-salience isolated nodes.

        输入:
            scope_id: 作用域 ID。
        输出:
            int: 被剪枝节点数。
        示例:
            示例输入: graph.prune("scope")
            示例输出: 0
        """
        nodes = self._nodes.get(scope_id, {})
        edges = self._edges.get(scope_id, [])
        degree = defaultdict(int)
        for edge in edges:
            degree[edge.source_id] += 1
            degree[edge.target_id] += 1
        removed = 0
        for node_id, node in list(nodes.items()):
            node.salience = salience_update(
                node.salience,
                ref_count=len(node.evidence_ids),
                edge_weight_sum=sum(
                    edge.weight
                    for edge in edges
                    if edge.source_id == node_id or edge.target_id == node_id
                ),
                decay=self.config.graph_salience_decay,
            )
            if (
                node.salience < self.config.graph_prune_threshold
                and degree[node_id] == 0
            ):
                del nodes[node_id]
                removed += 1
        return removed

    def mark_evidence_stale(self, scope_id: str, evidence_ids: List[str]) -> int:
        """Mark insight nodes superseded when their evidence changed.

        输入:
            scope_id: 作用域 ID。
            evidence_ids: 已被替换或失效的证据 ID。
        输出:
            int: 被标记为 superseded 的节点数量。
        示例:
            示例输入: graph.mark_evidence_stale("scope", ["m1"])
            示例输出: 1
        """
        affected = set(evidence_ids)
        if not affected:
            return 0
        changed = 0
        for node in self._nodes.get(scope_id, {}).values():
            if node.node_type == NodeType.INSIGHT and affected.intersection(
                node.evidence_ids
            ):
                node.status = InsightStatus.SUPERSEDED
                changed += 1
        return changed

    def audit(self, scope_id: str, repair: bool = True) -> Dict[str, int]:
        """Audit graph consistency and optionally repair orphan edges.

        输入:
            scope_id: 作用域 ID。
            repair: 是否移除端点缺失的孤儿边。
        输出:
            dict: checked_nodes、checked_edges、orphan_edges、removed_edges 等统计。
        示例:
            示例输入: graph.audit("scope", repair=True)
            示例输出: {"checked_nodes": 3, "checked_edges": 2, "orphan_edges": 0, ...}
        """
        nodes = self._nodes.get(scope_id, {})
        edges = self._edges.get(scope_id, [])
        node_ids: Set[str] = set(nodes)
        orphan_edges = [
            edge
            for edge in edges
            if edge.source_id not in node_ids or edge.target_id not in node_ids
        ]
        low_salience_nodes = [
            node
            for node in nodes.values()
            if node.salience < self.config.graph_prune_threshold
        ]
        superseded_insights = [
            node
            for node in nodes.values()
            if node.node_type == NodeType.INSIGHT
            and node.status == InsightStatus.SUPERSEDED
        ]
        removed_edges = 0
        if repair and orphan_edges:
            orphan_ids = {
                (edge.source_id, edge.target_id, edge.edge_type)
                for edge in orphan_edges
            }
            self._edges[scope_id] = [
                edge
                for edge in edges
                if (edge.source_id, edge.target_id, edge.edge_type) not in orphan_ids
            ]
            removed_edges = len(orphan_edges)
        return {
            "checked_nodes": len(nodes),
            "checked_edges": len(edges),
            "orphan_edges": len(orphan_edges),
            "removed_edges": removed_edges,
            "low_salience_nodes": len(low_salience_nodes),
            "superseded_insights": len(superseded_insights),
        }

    def all_nodes(self, scope_id: str) -> List[GraphNode]:
        """List all graph nodes for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[GraphNode]: 节点列表。
        示例:
            示例输入: graph.all_nodes("scope")
            示例输出: [GraphNode(...), ...]
        """
        return list(self._nodes.get(scope_id, {}).values())

    def all_edges(self, scope_id: str) -> List[GraphEdge]:
        """List all graph edges for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[GraphEdge]: 边列表。
        示例:
            示例输入: graph.all_edges("scope")
            示例输出: [GraphEdge(...), ...]
        """
        return list(self._edges.get(scope_id, []))

    def _upsert_node(
        self,
        scope_id: str,
        label: str,
        node_type: NodeType,
        evidence_ids: List[str],
        salience: float,
        mem_type: MemoryType = MemoryType.SEMANTIC,
    ) -> GraphNode:
        """Create or update a graph node by normalized label.

        输入:
            scope_id: 作用域 ID。
            label: 节点标签。
            node_type: 节点类型。
            evidence_ids: 证据 ID。
            salience: 显著度。
            mem_type: 逻辑记忆类型。
        输出:
            GraphNode: 节点对象。
        示例:
            示例输入: graph._upsert_node("scope", "Agent", NodeType.ENTITY, [], 0.5)
            示例输出: GraphNode(label="Agent", node_type=NodeType.ENTITY, ...)
        """
        key = f"{node_type.value}:{label.lower()}"
        existing_id = self._label_index[scope_id].get(key)
        if existing_id is not None:
            node = self._nodes[scope_id][existing_id]
            node.salience = max(node.salience, salience)
            if (
                node.mem_type == MemoryType.SEMANTIC
                and mem_type != MemoryType.SEMANTIC
            ):
                node.mem_type = mem_type
            for evidence_id in evidence_ids:
                if evidence_id not in node.evidence_ids:
                    node.evidence_ids.append(evidence_id)
            return node
        node_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{scope_id}:{key}"))
        node = GraphNode(
            node_id=node_id,
            node_type=node_type,
            label=label,
            scope_id=scope_id,
            salience=salience,
            evidence_ids=list(evidence_ids),
            mem_type=mem_type,
        )
        self._nodes[scope_id][node_id] = node
        self._label_index[scope_id][key] = node_id
        return node

    def _upsert_edge(
        self,
        scope_id: str,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        weight: float,
    ) -> GraphEdge:
        """Create or update a graph edge.

        输入:
            scope_id: 作用域 ID。
            source_id: 起点 ID。
            target_id: 终点 ID。
            edge_type: 边类型。
            weight: 边权重。
        输出:
            GraphEdge: 边对象。
        示例:
            示例输入: graph._upsert_edge("scope", "a", "b", EdgeType.SIMILAR, 0.5)
            示例输出:
                GraphEdge(source_id="a", target_id="b", edge_type=EdgeType.SIMILAR, ...)
        """
        for edge in self._edges[scope_id]:
            if (
                edge.source_id == source_id
                and edge.target_id == target_id
                and edge.edge_type == edge_type
            ):
                edge.weight = max(edge.weight, weight)
                return edge
        edge = GraphEdge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            scope_id=scope_id,
            weight=weight,
        )
        self._edges[scope_id].append(edge)
        return edge

    def _serialize(
        self, nodes: List[GraphNode], edges: List[GraphEdge]
    ) -> Dict[str, List[dict]]:
        """Serialize graph elements.

        输入:
            nodes: 节点列表。
            edges: 边列表。
        输出:
            dict: nodes 与 edges。
        示例:
            示例输入: graph._serialize([], [])
            示例输出: {"nodes": [], "edges": []}
        """
        node_ids = {node.node_id for node in nodes}
        filtered_edges = [
            edge
            for edge in edges
            if edge.source_id in node_ids and edge.target_id in node_ids
        ]
        return {
            "nodes": [node.to_dict() for node in nodes],
            "edges": [edge.to_dict() for edge in filtered_edges],
        }
