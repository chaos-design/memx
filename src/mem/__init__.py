"""MemX package with decoupled Port/Adapter memory backends."""

from .adapters import MemoryBackendBundle, build_memory_backend
from .agents.service import AgentMemory
from .api import HumanMem
from .config import MemoryConfig, load_memory_config

# 包级公共 API，仅暴露统一服务入口和配置对象。
__all__ = [
    "AgentMemory",
    "HumanMem",
    "MemoryBackendBundle",
    "MemoryConfig",
    "build_memory_backend",
    "load_memory_config",
]
