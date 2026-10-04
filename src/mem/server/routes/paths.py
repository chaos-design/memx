"""HTTP route path constants for the MemX server."""

from __future__ import annotations

HEALTH_PATH = "/health"
CONFIG_PATH = "/config"

MEMORY_OBSERVE_PATH = "/memory/observe"
MEMORY_MEMORIZE_PATH = "/memory/memorize"
MEMORY_RECALL_PATH = "/memory/recall"
MEMORY_SEARCH_PATH = "/memory/search"
MEMORY_UPDATE_PATH = "/memory/update"
MEMORY_FORGET_PATH = "/memory/forget"
MEMORY_REFLECT_PATH = "/memory/reflect"

MAINTENANCE_RUN_PATH = "/maintenance/run"

CONFIG_ROUTE_PATHS = (CONFIG_PATH,)
HEALTH_ROUTE_PATHS = (HEALTH_PATH,)
MAINTENANCE_ROUTE_PATHS = (MAINTENANCE_RUN_PATH,)
MEMORY_ROUTE_PATHS = (
    MEMORY_OBSERVE_PATH,
    MEMORY_MEMORIZE_PATH,
    MEMORY_RECALL_PATH,
    MEMORY_SEARCH_PATH,
    MEMORY_UPDATE_PATH,
    MEMORY_FORGET_PATH,
    MEMORY_REFLECT_PATH,
)
