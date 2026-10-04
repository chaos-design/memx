"""L1 working memory model definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..config.prompts import PromptSectionKey, render_prompt_line


@dataclass
class WorkingMemory:
    """Structured L1 working memory snapshot."""

    session_id: str
    rolling_summary: str = ""
    open_slots: List[Dict[str, Any]] = field(default_factory=list)
    mentioned_entities: List[str] = field(default_factory=list)
    token_used: int = 0
    last_compress_ts: float = 0.0
    scope_id: str = "default"

    def __post_init__(self) -> None:
        """Validate the L1 snapshot.

        输入:
            self: L1 工作记忆对象。
        输出:
            None；非法字段会抛出 ValueError。
        示例:
            示例输入: WorkingMemory("s1")
            示例输出: WorkingMemory 对象完成初始化，无异常。
        """
        if not self.session_id:
            msg = "session_id must not be empty."
            raise ValueError(msg)
        if not self.scope_id:
            msg = "scope_id must not be empty."
            raise ValueError(msg)
        if self.token_used < 0:
            msg = "token_used must be non-negative."
            raise ValueError(msg)

    def to_context(self) -> str:
        """Render L1 memory as prompt context.

        输入:
            self: L1 工作记忆对象。
        输出:
            str: 上下文文本。
        示例:
            示例输入: WorkingMemory("s1", rolling_summary="A").to_context()
            示例输出: "Conversation Summary: A"
        """
        parts = []
        if self.rolling_summary:
            parts.append(
                render_prompt_line(PromptSectionKey.SUMMARY, self.rolling_summary)
            )
        if self.open_slots:
            parts.append(
                render_prompt_line(PromptSectionKey.OPEN_SLOTS, repr(self.open_slots))
            )
        if self.mentioned_entities:
            parts.append(
                render_prompt_line(
                    PromptSectionKey.ENTITIES,
                    ", ".join(self.mentioned_entities),
                )
            )
        return "\n".join(parts)
