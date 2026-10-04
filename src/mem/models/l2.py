"""L2 episodic memory model definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from .enums import MemoryStatus, MemoryType


@dataclass
class EpisodicMemory:
    """L2 episodic vector memory record."""

    mem_id: str
    embedding: Tuple[float, ...]
    text: str
    importance: int
    ts_create: float
    ts_last_access: float
    scope_id: str
    access_count: int = 0
    stability: float = 86_400.0
    status: MemoryStatus = MemoryStatus.ACTIVE
    source_ids: List[str] = field(default_factory=list)
    mem_type: MemoryType = MemoryType.EPISODIC

    def __post_init__(self) -> None:
        """Validate L2 memory fields.

        输入:
            self: L2 记忆对象。
        输出:
            None；非法字段会抛出 ValueError。
        示例:
            示例输入: EpisodicMemory("m1", (1.0,), "text", 5, 1.0, 1.0, "s")
            示例输出: EpisodicMemory 对象完成初始化，无异常。
        """
        if not self.mem_id:
            msg = "mem_id must not be empty."
            raise ValueError(msg)
        if not self.text:
            msg = "text must not be empty."
            raise ValueError(msg)
        if not 0 <= self.importance <= 10:
            msg = "importance must be in [0, 10]."
            raise ValueError(msg)
        if self.access_count < 0:
            msg = "access_count must be non-negative."
            raise ValueError(msg)
        if self.stability <= 0:
            msg = "stability must be positive."
            raise ValueError(msg)
        if not self.scope_id:
            msg = "scope_id must not be empty."
            raise ValueError(msg)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the L2 record.

        输入:
            self: L2 记忆对象。
        输出:
            dict: 可序列化字段。
        示例:
            示例输入: memory.to_dict()
            示例输出: {"mem_id": "m1", "text": "text", "status": "active", ...}
        """
        return {
            "mem_id": self.mem_id,
            "text": self.text,
            "importance": self.importance,
            "ts_create": self.ts_create,
            "ts_last_access": self.ts_last_access,
            "scope_id": self.scope_id,
            "access_count": self.access_count,
            "stability": self.stability,
            "status": self.status.value,
            "source_ids": list(self.source_ids),
            "mem_type": self.mem_type.value,
        }
