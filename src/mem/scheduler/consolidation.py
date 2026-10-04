"""Scheduled consolidation task implementation."""

from __future__ import annotations

from typing import Any, Dict


def run_consolidation(
    memory: Any,
    scope_id: str = "human_mem_project",
    force: bool = False,
) -> Dict[str, Any]:
    """Run memory consolidation for the project memory scope.

    输入:
        memory: AgentMemory-compatible service.
        scope_id: internal project memory scope.
        force: whether to bypass consolidation thresholds.
    输出:
        dict: consolidation result.
    示例:
        示例输入: run_consolidation(memory, "human_mem_project", force=True)
        示例输出: {"n_facts": 1, "n_insights": 1, ...}
    """
    return memory.reflect(scope_id, force=force)
