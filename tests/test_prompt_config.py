"""Tests for centralized prompt context configuration."""

from __future__ import annotations

from mem.agents.prompts import render_episodes_context, render_facts_context
from mem.config.prompts import (
    PROMPT_SECTIONS,
    PromptSectionKey,
    prompt_section_label,
    render_custom_prompt_values,
    render_prompt_line,
    render_prompt_values,
)
from mem.models.l1 import WorkingMemory


def test_prompt_sections_are_professional_and_centralized() -> None:
    """Verify prompt copy is managed through the central config module.

    输入:
        无；测试读取集中化 prompt 配置。
    输出:
        None；断言关键 prompt 标题由统一配置提供。
    Example Input:
        pytest tests/test_prompt_config.py
    Example Output:
        测试通过。
    """
    assert PROMPT_SECTIONS[PromptSectionKey.FACTS].label == "Verified Facts"
    assert PROMPT_SECTIONS[PromptSectionKey.EPISODES].label == "Relevant Episodes"
    assert prompt_section_label(PromptSectionKey.SUMMARY) == "Conversation Summary"
    assert "long-term memory" in PROMPT_SECTIONS[PromptSectionKey.FACTS].purpose


def test_prompt_renderers_use_managed_copy() -> None:
    """Verify runtime prompt helpers load copy from centralized config.

    输入:
        无；测试 L1、facts、episodes 三类 prompt context。
    输出:
        None；断言运行时渲染结果使用集中管理后的专业化标题。
    Example Input:
        render_facts_context(["zh"])
    Example Output:
        "Verified Facts: ['zh']"
    """
    working = WorkingMemory(
        "s1",
        rolling_summary="User prefers concise Chinese answers.",
        open_slots=[{"topic": "deployment", "status": "pending"}],
        mentioned_entities=["MemX", "pytest"],
    )
    context = working.to_context()

    assert render_prompt_line(PromptSectionKey.SUMMARY, "A") == (
        "Conversation Summary: A"
    )
    assert render_prompt_values(PromptSectionKey.FACTS, ["zh"]) == (
        "Verified Facts: ['zh']"
    )
    assert render_facts_context(["zh"]) == "Verified Facts: ['zh']"
    assert render_episodes_context(["remember x"]) == (
        "Relevant Episodes: ['remember x']"
    )
    assert "Conversation Summary:" in context
    assert "Open Memory Slots:" in context
    assert "Mentioned Entities: MemX, pytest" in context


def test_prompt_renderers_omit_empty_sections() -> None:
    """Verify empty prompt sections are omitted cleanly.

    输入:
        无；测试空值、空序列和空自定义标题。
    输出:
        None；断言空 prompt 不污染上下文。
    Example Input:
        render_prompt_values(PromptSectionKey.FACTS, [])
    Example Output:
        ""
    """
    assert render_prompt_line(PromptSectionKey.SUMMARY, " ") == ""
    assert render_prompt_values(PromptSectionKey.FACTS, []) == ""
    assert render_custom_prompt_values(" ", ["x"]) == "['x']"
    assert WorkingMemory("s1").to_context() == ""
