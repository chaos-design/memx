"""Recall response and planning model definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .l2 import EpisodicMemory
from .l3 import SemanticFact


@dataclass
class RecallResult:
    """Unified recall response payload."""

    facts: List[SemanticFact]
    episodes: List[EpisodicMemory]
    subgraph: Dict[str, List[Dict[str, Any]]]
    reinforced: List[str]
    plan: Optional["RecallPlan"] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize recall result for API callers.

        输入:
            self: 召回结果对象。
        输出:
            dict: facts、episodes、subgraph 与 reinforced。
        示例:
            示例输入: result.to_dict()
            示例输出: {"facts": [...], "episodes": [...], "subgraph": {...}, ...}
        """
        payload = {
            "facts": [fact.to_dict() for fact in self.facts],
            "episodes": [memory.to_dict() for memory in self.episodes],
            "subgraph": self.subgraph,
            "reinforced": list(self.reinforced),
        }
        if self.plan is not None:
            payload["plan"] = self.plan.to_dict()
        return payload


@dataclass
class RecallPlan:
    """Recall route plan produced by RecallAgent."""

    scope_id: str
    query: str
    k: int
    routes: List[str] = field(default_factory=list)
    include_preferences: bool = True
    include_graph: bool = True

    def __post_init__(self) -> None:
        """Validate recall plan fields.

        输入:
            self: 召回计划对象。
        输出:
            None；非法字段会抛出 ValueError。
        示例:
            示例输入: RecallPlan("scope", "query", 8)
            示例输出: RecallPlan 对象完成初始化，无异常。
        """
        if not self.scope_id:
            msg = "scope_id must not be empty."
            raise ValueError(msg)
        if self.k <= 0:
            msg = "k must be positive."
            raise ValueError(msg)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the recall plan.

        输入:
            self: 召回计划对象。
        输出:
            dict: 可序列化的路由计划。
        示例:
            示例输入: RecallPlan("scope", "q", 3, ["l2"]).to_dict()
            示例输出: {"scope_id": "scope", "query": "q", "k": 3, ...}
        """
        return {
            "scope_id": self.scope_id,
            "query": self.query,
            "k": self.k,
            "routes": list(self.routes),
            "include_preferences": self.include_preferences,
            "include_graph": self.include_graph,
        }
