"""L4 cognitive graph model definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .enums import EdgeType, InsightStatus, MemoryType, NodeType


@dataclass
class GraphNode:
    """L4 graph node."""

    node_id: str
    node_type: NodeType
    label: str
    scope_id: str
    salience: float = 0.5
    evidence_ids: List[str] = field(default_factory=list)
    status: InsightStatus = InsightStatus.ACTIVE
    mem_type: MemoryType = MemoryType.SEMANTIC

    def __post_init__(self) -> None:
        """Validate graph node fields.

        输入:
            self: L4 节点对象。
        输出:
            None；非法字段会抛出 ValueError。
        示例:
            示例输入: GraphNode("n1", NodeType.ENTITY, "Agent", "scope")
            示例输出: GraphNode 对象完成初始化，无异常。
        """
        if not self.node_id:
            msg = "node_id must not be empty."
            raise ValueError(msg)
        if not self.label:
            msg = "label must not be empty."
            raise ValueError(msg)
        if not self.scope_id:
            msg = "scope_id must not be empty."
            raise ValueError(msg)
        if not 0 <= self.salience <= 1:
            msg = "salience must be in [0, 1]."
            raise ValueError(msg)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph node fields.

        输入:
            self: L4 节点对象。
        输出:
            dict: 可序列化字段。
        示例:
            示例输入: node.to_dict()
            示例输出: {"id": "n1", "type": "entity", "label": "Agent", ...}
        """
        return {
            "id": self.node_id,
            "type": self.node_type.value,
            "label": self.label,
            "scope_id": self.scope_id,
            "salience": self.salience,
            "evidence_ids": list(self.evidence_ids),
            "status": self.status.value,
            "mem_type": self.mem_type.value,
        }


@dataclass
class GraphEdge:
    """L4 graph edge."""

    source_id: str
    target_id: str
    edge_type: EdgeType
    scope_id: str
    weight: float = 0.5

    def __post_init__(self) -> None:
        """Validate graph edge fields.

        输入:
            self: L4 边对象。
        输出:
            None；非法字段会抛出 ValueError。
        示例:
            示例输入: GraphEdge("a", "b", EdgeType.SIMILAR, "scope")
            示例输出: GraphEdge 对象完成初始化，无异常。
        """
        if not self.source_id or not self.target_id:
            msg = "edge endpoints must not be empty."
            raise ValueError(msg)
        if not self.scope_id:
            msg = "scope_id must not be empty."
            raise ValueError(msg)
        if not 0 <= self.weight <= 1:
            msg = "weight must be in [0, 1]."
            raise ValueError(msg)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph edge fields.

        输入:
            self: L4 边对象。
        输出:
            dict: 可序列化字段。
        示例:
            示例输入: edge.to_dict()
            示例输出: {"source": "a", "target": "b", "type": "similar", ...}
        """
        return {
            "source": self.source_id,
            "target": self.target_id,
            "type": self.edge_type.value,
            "scope_id": self.scope_id,
            "weight": self.weight,
        }
