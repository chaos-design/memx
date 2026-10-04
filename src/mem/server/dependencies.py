"""Shared FastAPI dependencies for the MemX server."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request

from ..api import HumanMem


def memory_from_request(request: Request) -> HumanMem:
    """Return the request-scoped HumanMem service.

    输入:
        request: FastAPI request object.
    输出:
        HumanMem: application-scoped HumanMem instance.
    示例:
        示例输入: memory_from_request(request)
        示例输出: HumanMem(...)
    """
    memory = getattr(request.app.state, "human_mem", None)
    if not isinstance(memory, HumanMem):
        raise HTTPException(status_code=500, detail="HumanMem is not initialized")
    return memory


def config_path_from_request(request: Request) -> Optional[str]:
    """Return the configured hms.json path from app state.

    输入:
        request: FastAPI request object.
    输出:
        str | None: configured hms.json path, when one was provided.
    示例:
        示例输入: config_path_from_request(request)
        示例输出: "/tmp/hms.json"
    """
    return getattr(request.app.state, "config_path", None)
