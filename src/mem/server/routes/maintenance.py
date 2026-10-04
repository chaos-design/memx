"""Maintenance routes for the MemX server."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request

from ..dependencies import memory_from_request
from ..schemas import MaintenanceRequest
from .paths import MAINTENANCE_RUN_PATH

router = APIRouter(tags=["maintenance"])


@router.post(MAINTENANCE_RUN_PATH)
def run_maintenance(request: Request, payload: MaintenanceRequest) -> Dict[str, Any]:
    """Run one maintenance batch.

    输入:
        request: FastAPI request object.
        payload: maintenance request body.
    输出:
        dict: maintenance result.
    示例:
        示例输入: POST /maintenance/run
        示例输出: {"scope_id": "human_mem_project", "tasks": {...}}
    """
    return memory_from_request(request).maintenance(
        tasks=payload.tasks,
        force_reflect=payload.force_reflect,
    )
