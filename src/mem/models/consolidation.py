"""Consolidation queue model definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .enums import InboxStatus, MemoryType


@dataclass
class ConsolidationInboxItem:
    """Pending item consumed by the ConsolidationAgent."""

    item_id: str
    scope_id: str
    mem_id: str
    text: str
    priority: float
    ts_enqueue: float
    mem_type_hint: MemoryType = MemoryType.EPISODIC
    status: InboxStatus = InboxStatus.PENDING
    retry_count: int = 0
    last_error: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate inbox item fields.

        输入:
            self: inbox 条目对象。
        输出:
            None；非法字段会抛出 ValueError。
        示例:
            示例输入: ConsolidationInboxItem("i1", "scope", "m1", "text", 8, 1.0)
            示例输出: ConsolidationInboxItem 对象完成初始化，无异常。
        """
        if not self.item_id:
            msg = "item_id must not be empty."
            raise ValueError(msg)
        if not self.scope_id:
            msg = "scope_id must not be empty."
            raise ValueError(msg)
        if not self.mem_id:
            msg = "mem_id must not be empty."
            raise ValueError(msg)
        if not self.text:
            msg = "text must not be empty."
            raise ValueError(msg)
        if self.retry_count < 0:
            msg = "retry_count must be non-negative."
            raise ValueError(msg)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the inbox item.

        输入:
            self: inbox 条目对象。
        输出:
            dict: 可序列化字段。
        示例:
            示例输入: item.to_dict()
            示例输出: {"item_id": "i1", "status": "pending", ...}
        """
        return {
            "item_id": self.item_id,
            "scope_id": self.scope_id,
            "mem_id": self.mem_id,
            "text": self.text,
            "priority": self.priority,
            "ts_enqueue": self.ts_enqueue,
            "mem_type_hint": self.mem_type_hint.value,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
        }
