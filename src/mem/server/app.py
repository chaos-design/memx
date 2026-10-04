"""FastAPI app factory for MemX."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI

from ..api import HumanMem
from ..config import load_memory_config
from .errors import register_exception_handlers
from .routes import api_router


def create_app(
    memory: Optional[HumanMem] = None,
    config_path: Optional[str] = None,
) -> FastAPI:
    """Create a FastAPI app backed by HumanMem.

    输入:
        memory: optional HumanMem instance.
        config_path: optional hms.json path.
    输出:
        FastAPI: runnable HTTP API application.
    示例:
        示例输入: create_app(HumanMem())
        示例输出: FastAPI(...)
    """
    app = FastAPI(title="MemX API", version="0.1.0")
    app.state.config_path = config_path
    app.state.human_mem = memory or HumanMem(load_memory_config(path=config_path))
    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()
