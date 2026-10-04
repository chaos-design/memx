"""Custom exceptions and API error helpers for MemX."""

from __future__ import annotations

from typing import Any, Dict


class HumanMemoryError(Exception):
    """Base exception for package-specific errors."""


class ConfigurationError(HumanMemoryError, ValueError):
    """Raised when configuration input cannot produce a valid MemoryConfig."""


class ValidationError(HumanMemoryError, ValueError):
    """Raised when caller input violates public API validation rules."""


class MemoryNotFoundError(HumanMemoryError, KeyError):
    """Raised when a requested memory record does not exist."""


class ProtectedMemoryError(HumanMemoryError, PermissionError):
    """Raised when an operation targets a protected memory without force."""


class BackendDependencyError(HumanMemoryError, RuntimeError):
    """Raised when a production backend dependency is missing or unavailable."""


class ApiError(HumanMemoryError):
    """Raised for HTTP API level errors before FastAPI conversion."""


def error_type(exc: Exception) -> str:
    """Return a stable error type name for an exception.

    输入:
        exc: 异常实例。
    输出:
        str: 异常类型名。
    示例:
        示例输入: error_type(ValidationError("bad"))
        示例输出: "ValidationError"
    """
    return exc.__class__.__name__


def error_payload(exc: Exception) -> Dict[str, Any]:
    """Convert an exception into an API-friendly payload.

    输入:
        exc: 异常实例。
    输出:
        dict: 包含 error.type 和 error.message 的响应体。
    示例:
        示例输入: error_payload(ValidationError("bad"))
        示例输出: {"error": {"type": "ValidationError", "message": "bad"}}
    """
    return {"error": {"type": error_type(exc), "message": str(exc)}}
