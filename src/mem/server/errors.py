"""HTTP error handling for the MemX server."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ..exceptions import HumanMemoryError, error_payload


def register_exception_handlers(app: FastAPI) -> None:
    """Register server-level exception handlers.

    输入:
        app: FastAPI application.
    输出:
        None.
    示例:
        示例输入: register_exception_handlers(app)
        示例输出: None
    """

    @app.exception_handler(HumanMemoryError)
    async def human_memory_error_handler(
        _request: Any,
        exc: HumanMemoryError,
    ) -> JSONResponse:
        """Convert package errors into HTTP 400 responses.

        输入:
            _request: FastAPI request object.
            exc: HumanMemoryError exception.
        输出:
            JSONResponse: serialized error response.
        示例:
            示例输入: human_memory_error_handler(request, exc)
            示例输出: JSONResponse(status_code=400, ...)
        """
        return JSONResponse(status_code=400, content=error_payload(exc))
