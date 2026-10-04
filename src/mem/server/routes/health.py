"""Health-check routes for the MemX server."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request

from ...api import HumanMem
from ...embedding.vector import embed_text
from ..dependencies import memory_from_request
from .paths import HEALTH_PATH

router = APIRouter(tags=["health"])


@router.get(HEALTH_PATH)
def health(request: Request) -> Dict[str, Any]:
    """Return server health and operational dependency status.

    输入:
        request: FastAPI request object.
    输出:
        dict: health, scheduler, and embedding status.
    示例:
        示例输入: GET /health
        示例输出: {"status": "ok", "scheduler": {...}, "embedding": {...}}
    """
    memory = memory_from_request(request)
    return {
        "status": "ok",
        "scheduler": memory.scheduler_status(),
        "embedding": _embedding_status(memory),
    }


def _embedding_status(memory: HumanMem) -> Dict[str, Any]:
    """Return local embedding subsystem status.

    输入:
        memory: HumanMem instance.
    输出:
        dict: embedding implementation status.
    示例:
        示例输入: _embedding_status(memory)
        示例输出: {"status": "ok", "provider": "deterministic_local", ...}
    """
    dimensions = memory.memory.config.embedding_dimensions
    vector = embed_text("healthcheck", dimensions)
    return {
        "status": "ok",
        "provider": "deterministic_local",
        "dimensions": dimensions,
        "vector_dimensions": len(vector),
    }
