"""Small helpers for model normalization."""

from __future__ import annotations

from typing import List, Optional, Sequence


def ensure_sequence(value: Optional[Sequence[str]]) -> List[str]:
    """Convert an optional string sequence into a list.

    输入:
        value: 字符串序列或 None。
    输出:
        list[str]: 新列表。
    示例:
        示例输入: ensure_sequence(("a", "b"))
        示例输出: ["a", "b"]
    """
    if value is None:
        return []
    return list(value)
