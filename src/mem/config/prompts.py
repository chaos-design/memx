"""Centralized prompt copy and rendering helpers for memory context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class PromptSectionKey(str, Enum):
    """Stable keys for prompt context sections."""

    SUMMARY = "summary"
    OPEN_SLOTS = "open_slots"
    ENTITIES = "entities"
    FACTS = "facts"
    EPISODES = "episodes"


@dataclass(frozen=True)
class PromptSectionTemplate:
    """Prompt section metadata managed in one place."""

    label: str
    purpose: str


PROMPT_SECTIONS: Mapping[PromptSectionKey, PromptSectionTemplate] = {
    PromptSectionKey.SUMMARY: PromptSectionTemplate(
        label="Conversation Summary",
        purpose="Condensed working-memory summary for the active session.",
    ),
    PromptSectionKey.OPEN_SLOTS: PromptSectionTemplate(
        label="Open Memory Slots",
        purpose="Unresolved working-memory items that may need later closure.",
    ),
    PromptSectionKey.ENTITIES: PromptSectionTemplate(
        label="Mentioned Entities",
        purpose="Entity names already observed in the active session.",
    ),
    PromptSectionKey.FACTS: PromptSectionTemplate(
        label="Verified Facts",
        purpose="High-confidence semantic facts recalled from long-term memory.",
    ),
    PromptSectionKey.EPISODES: PromptSectionTemplate(
        label="Relevant Episodes",
        purpose="Episodic evidence recalled for the current query.",
    ),
}


def prompt_section_label(section_key: PromptSectionKey) -> str:
    """Return the managed display label for a prompt section.

    输入:
        section_key: Prompt section enum key。
    输出:
        str: 专业化 prompt 区块标题。
    Example Input:
        prompt_section_label(PromptSectionKey.FACTS)
    Example Output:
        "Verified Facts"
    """
    return PROMPT_SECTIONS[section_key].label


def render_prompt_line(section_key: PromptSectionKey, content: object) -> str:
    """Render one managed prompt section line.

    输入:
        section_key: Prompt section enum key。
        content: 已格式化的区块内容。
    输出:
        str: 可直接拼入 Agent prompt 的上下文行；空内容返回空字符串。
    Example Input:
        render_prompt_line(PromptSectionKey.SUMMARY, "User prefers concise output.")
    Example Output:
        "Conversation Summary: User prefers concise output."
    """
    if content is None:
        return ""
    text = str(content).strip()
    if not text:
        return ""
    return f"{prompt_section_label(section_key)}: {text}"


def render_prompt_values(
    section_key: PromptSectionKey,
    values: Iterable[object],
) -> str:
    """Render structured values under a managed prompt section label.

    输入:
        section_key: Prompt section enum key。
        values: 待渲染的结构化值序列。
    输出:
        str: 可直接拼入 Agent prompt 的上下文行；空序列返回空字符串。
    Example Input:
        render_prompt_values(PromptSectionKey.FACTS, ["zh"])
    Example Output:
        "Verified Facts: ['zh']"
    """
    items = list(values)
    if not items:
        return ""
    return render_prompt_line(section_key, repr(items))


def render_custom_prompt_values(label: str, values: Iterable[object]) -> str:
    """Render values with an explicit custom prompt label.

    输入:
        label: 调用方传入的自定义区块标题。
        values: 待渲染的结构化值序列。
    输出:
        str: 自定义标题的 prompt 上下文行；空序列返回空字符串。
    Example Input:
        render_custom_prompt_values("Diagnostics", ["ok"])
    Example Output:
        "Diagnostics: ['ok']"
    """
    items = list(values)
    if not items:
        return ""
    clean_label = label.strip()
    if not clean_label:
        return repr(items)
    return f"{clean_label}: {items!r}"
