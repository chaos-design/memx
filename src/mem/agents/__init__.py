"""Agent-facing orchestration modules."""

from .consolidation import ConsolidationAgent
from .recall import RecallAgent

__all__ = [
    "AgentMemory",
    "ConsolidationAgent",
    "RecallAgent",
]


def __getattr__(name: str) -> object:
    """Lazily expose AgentMemory without introducing an import cycle.

    输入:
        name: 需要解析的属性名。
    输出:
        object: 对应导出对象。
    示例:
        示例输入: getattr(mem.agents, "AgentMemory")
        示例输出: AgentMemory 类。
    """
    if name == "AgentMemory":
        from .service import AgentMemory

        return AgentMemory
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
