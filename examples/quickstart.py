"""Minimal MemX usage example."""

from __future__ import annotations

from mem import AgentMemory, MemoryConfig


def main() -> None:
    """Run a small observe, reflect, and recall workflow.

    输入:
        无。
    输出:
        None；示例会在终端打印召回的事实列表。
    示例:
        示例输入: main()
        示例输出: [{"fact_key": "user.lang_pref", "value": "zh", ...}]
    """
    memory = AgentMemory(MemoryConfig(flush_turns=2))
    scope_id = "quickstart-scope"
    session_id = "quickstart-session"

    memory.observe(
        session_id,
        {"role": "user", "content": "记住 user.lang_pref=zh，语言偏好是中文"},
        scope_id=scope_id,
    )
    memory.reflect(scope_id, force=True)
    recalled = memory.recall(session_id, "user.lang_pref", scope_id=scope_id)

    print(recalled["facts"])


if __name__ == "__main__":
    main()
