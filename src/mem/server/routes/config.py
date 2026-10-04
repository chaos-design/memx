"""Configuration routes for the MemX server."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request

from ...api import HumanMem
from ...config import load_memory_config, read_hms_config, write_hms_config
from ..dependencies import config_path_from_request
from ..schemas import ConfigPatchRequest
from .paths import CONFIG_PATH

router = APIRouter(tags=["config"])


@router.get(CONFIG_PATH)
def get_config(request: Request) -> Dict[str, Any]:
    """Return current hms.json config.

    输入:
        request: FastAPI request object.
    输出:
        dict: current configuration.
    示例:
        示例输入: GET /config
        示例输出: {"max_recall_k": 50, ...}
    """
    return read_hms_config(config_path_from_request(request))


@router.patch(CONFIG_PATH)
def patch_config(request: Request, payload: ConfigPatchRequest) -> Dict[str, Any]:
    """Patch hms.json and reload the server memory service.

    输入:
        request: FastAPI request object.
        payload: configuration patch request.
    输出:
        dict: updated configuration.
    示例:
        示例输入: PATCH /config {"updates": {"max_recall_k": 10}}
        示例输出: {"max_recall_k": 10, ...}
    """
    config_path = config_path_from_request(request)
    updated = write_hms_config(payload.updates, config_path)
    request.app.state.human_mem = HumanMem(load_memory_config(path=config_path))
    return updated
