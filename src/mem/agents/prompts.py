"""Prompt and context templates for Agent-facing memory output."""

from __future__ import annotations

from typing import Iterable

from ..config.prompts import (
    PromptSectionKey,
    render_custom_prompt_values,
    render_prompt_values,
)


def render_context_section(label: str, values: Iterable[object]) -> str:
    """Render a prompt context section from structured values.

    输入:
        label: 上下文区块标签。
        values: 要渲染的值序列。
    输出:
        str: 可插入 prompt 的单行上下文；空值返回空字符串。
    示例:
        示例输入: render_context_section("Facts", ["zh"])
        示例输出: "Facts: ['zh']"
    """
    return render_custom_prompt_values(label, values)


def render_facts_context(values: Iterable[object]) -> str:
    """Render recalled facts as prompt context.

    输入:
        values: fact value 序列。
    输出:
        str: facts prompt context。
    示例:
        示例输入: render_facts_context(["zh"])
        示例输出: "Verified Facts: ['zh']"
    """
    return render_prompt_values(PromptSectionKey.FACTS, values)


def render_episodes_context(values: Iterable[object]) -> str:
    """Render recalled episodes as prompt context.

    输入:
        values: episode text 序列。
    输出:
        str: episodes prompt context。
    示例:
        示例输入: render_episodes_context(["remember x"])
        示例输出: "Relevant Episodes: ['remember x']"
    """
    return render_prompt_values(PromptSectionKey.EPISODES, values)
