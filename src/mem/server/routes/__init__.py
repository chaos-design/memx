"""Route package for the MemX FastAPI server."""

from __future__ import annotations

from fastapi import APIRouter

from .config import router as config_router
from .health import router as health_router
from .maintenance import router as maintenance_router
from .memory import router as memory_router
from .paths import (
    CONFIG_PATH,
    CONFIG_ROUTE_PATHS,
    HEALTH_PATH,
    HEALTH_ROUTE_PATHS,
    MAINTENANCE_ROUTE_PATHS,
    MAINTENANCE_RUN_PATH,
    MEMORY_FORGET_PATH,
    MEMORY_MEMORIZE_PATH,
    MEMORY_OBSERVE_PATH,
    MEMORY_RECALL_PATH,
    MEMORY_REFLECT_PATH,
    MEMORY_ROUTE_PATHS,
    MEMORY_SEARCH_PATH,
    MEMORY_UPDATE_PATH,
)

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(config_router)
api_router.include_router(memory_router)
api_router.include_router(maintenance_router)

__all__ = [
    "CONFIG_PATH",
    "CONFIG_ROUTE_PATHS",
    "HEALTH_PATH",
    "HEALTH_ROUTE_PATHS",
    "MAINTENANCE_ROUTE_PATHS",
    "MAINTENANCE_RUN_PATH",
    "MEMORY_FORGET_PATH",
    "MEMORY_MEMORIZE_PATH",
    "MEMORY_OBSERVE_PATH",
    "MEMORY_RECALL_PATH",
    "MEMORY_REFLECT_PATH",
    "MEMORY_ROUTE_PATHS",
    "MEMORY_SEARCH_PATH",
    "MEMORY_UPDATE_PATH",
    "api_router",
]
