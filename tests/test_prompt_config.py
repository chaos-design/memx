"""Tests for centralized prompt context configuration."""

from __future__ import annotations

import pytest

from mem import HumanMem, MemoryConfig
from mem.agents.prompts import (
    MEMORY_CONTEXT_INSTRUCTION,
    assemble_prompt_messages,
    render_episodes_context,
    render_facts_context,
)
from mem.config.prompts import (
    PROMPT_SECTIONS,
    PromptSectionKey,
    prompt_section_label,
    render_custom_prompt_values,
    render_prompt_line,
    render_prompt_values,
)
from mem.exceptions import ValidationError
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


def test_prompt_assembly_keeps_instruction_memory_and_input_separate() -> None:
    """Verify a complete prompt has stable roles and memory boundaries.

    输入:
        system prompt、召回上下文和当前用户问题。
    输出:
        三条 Chat API message，顺序为 system、memory system、user。
    Example Input:
        assemble_prompt_messages("Be concise.", "My language?", "Facts: zh")
    Example Output:
        [{"role": "system"}, {"role": "system"}, {"role": "user"}]
    """
    messages = assemble_prompt_messages(
        system_prompt=" Be concise. ",
        user_input=" My language? ",
        memory_context="Verified Facts: ['zh']",
    )

    assert messages == [
        {"role": "system", "content": "Be concise."},
        {
            "role": "system",
            "content": (
                f"{MEMORY_CONTEXT_INSTRUCTION}\n"
                "<memory_context>\n"
                "Verified Facts: ['zh']\n"
                "</memory_context>"
            ),
        },
        {"role": "user", "content": "My language?"},
    ]


def test_prompt_assembly_omits_empty_memory_context() -> None:
    """Verify first-turn prompts do not contain an empty memory message.

    输入:
        system prompt、用户输入、空 memory context。
    输出:
        仅包含 system 和 user 的两条 message。
    Example Input:
        assemble_prompt_messages("Be concise.", "Hello")
    Example Output:
        [{"role": "system", ...}, {"role": "user", ...}]
    """
    assert assemble_prompt_messages("Be concise.", "Hello") == [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Hello"},
    ]


@pytest.mark.parametrize(
    ("system_prompt", "user_input", "message"),
    [
        (" ", "Hello", "system_prompt must not be empty."),
        ("Be concise.", "\n", "user_input must not be empty."),
    ],
)
def test_prompt_assembly_rejects_empty_required_input(
    system_prompt: str,
    user_input: str,
    message: str,
) -> None:
    """Verify invalid assembly input fails before calling an LLM provider."""
    with pytest.raises(ValidationError, match=message):
        assemble_prompt_messages(system_prompt, user_input)


def test_human_mem_assembly_defaults_query_and_validates_before_recall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the public API uses clean user input and avoids invalid recalls."""
    memory = HumanMem(MemoryConfig(persist_on_write=False))
    context_calls = []

    def fake_get_context(session_id: str, query: str, scope_id: str) -> str:
        context_calls.append((session_id, query, scope_id))
        return "Verified Facts: ['zh']"

    monkeypatch.setattr(memory.memory, "get_context", fake_get_context)

    messages = memory.assemble_prompt(
        session_id="s1",
        user_input="  What is my language?  ",
        system_prompt="Answer concisely.",
    )

    assert context_calls == [
        ("s1", "What is my language?", "human_mem_project"),
    ]
    assert messages[-1] == {
        "role": "user",
        "content": "What is my language?",
    }

    with pytest.raises(ValidationError, match="user_input must not be empty"):
        memory.assemble_prompt("s1", " ", "Answer concisely.")
    assert len(context_calls) == 1
