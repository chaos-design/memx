"""Scheduled forgetting task implementation."""

from __future__ import annotations

from typing import Any, Dict


def run_forgetting_sweep(
    memory: Any,
    scope_id: str = "human_mem_project",
) -> Dict[str, Any]:
    """Run decay, pruning, and graph cleanup for the project memory scope.

    输入:
        memory: AgentMemory-compatible service.
        scope_id: internal project memory scope.
    输出:
        dict: forgetting and pruning result.
    示例:
        示例输入: run_forgetting_sweep(memory, "human_mem_project")
        示例输出: {"checked": 10.0, "archived": 1.0, ...}
    """
    return memory.forget_sweep(scope_id)
