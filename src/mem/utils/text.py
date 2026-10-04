"""Text helpers shared by API, retrieval, and persistence modules."""

from __future__ import annotations

import re
from typing import List

from ..constants import EXPLICIT_MEMORY_MARKERS
from ..embedding.vector import tokenize


def normalize_text(text: str) -> str:
    """Collapse whitespace in text.

    输入:
        text: 原始文本。
    输出:
        str: 空白归一化后的文本。
    示例:
        示例输入: normalize_text("a  b\\n c")
        示例输出: "a b c"
    """
    return " ".join(text.split())


def is_explicit_memory(text: str) -> bool:
    """Check whether text carries explicit memorize intent.

    输入:
        text: 用户文本。
    输出:
        bool: 是否包含记忆指令。
    示例:
        示例输入: is_explicit_memory("请记住 user.lang=zh")
        示例输出: True
    """
    lowered = text.lower()
    return any(
        marker in lowered or marker in text for marker in EXPLICIT_MEMORY_MARKERS
    )


def extract_entities(text: str, limit: int = 8) -> List[str]:
    """Extract lightweight entity labels from mixed Chinese and English text.

    输入:
        text: 记忆文本。
        limit: 最大返回数量。
    输出:
        list[str]: 去重后的实体标签。
    示例:
        示例输入: extract_entities("Agent 记忆系统")
        示例输出: ["agent", "记忆系统"]
    """
    entities = []
    for token in tokenize(text):
        if len(token) >= 2 and token not in entities:
            entities.append(token)
    for word in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if word not in entities:
            entities.append(word)
    return entities[:limit]


def insight_label(text: str, limit: int = 72) -> str:
    """Create a concise insight label from memory text.

    输入:
        text: 记忆文本。
        limit: 最大标签长度。
    输出:
        str: 截断后的洞察标签。
    示例:
        示例输入: insight_label("long text", limit=72)
        示例输出: "long text"
    """
    cleaned = normalize_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)] + "..."
