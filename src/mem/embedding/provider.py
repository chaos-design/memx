"""Embedding provider selection and vector validation."""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from ..config.settings import MemoryConfig
from ..exceptions import BackendDependencyError
from ..memory.ports import LLMGatewayPort
from .vector import embed_text

Embedder = Callable[[str, int], Tuple[float, ...]]

LOCAL_EMBEDDING_MODEL = "deterministic-token-hash-v1"


class EmbeddingRuntime:
    """Resolve one embedding implementation for every read and write path."""

    def __init__(
        self,
        config: MemoryConfig,
        gateway: Optional[LLMGatewayPort] = None,
    ) -> None:
        """Initialize the configured embedding runtime.

        输入:
            config: embedding 后端、模型和维度配置。
            gateway: gateway 模式使用的 LLM Gateway Port。
        输出:
            None。
        示例:
            示例输入: EmbeddingRuntime(MemoryConfig())
            示例输出: provider="local" 的 runtime。
        """
        self.config = config
        self.provider = self._resolve_provider(config)
        self.gateway = gateway
        if self.provider == "gateway" and self.gateway is None:
            msg = "embedding_backend='gateway' requires an LLM gateway."
            raise BackendDependencyError(msg)

    def embed(self, text: str, dimensions: int) -> Tuple[float, ...]:
        """Create and validate one embedding vector.

        输入:
            text: 待向量化文本。
            dimensions: 调用链要求的向量维度。
        输出:
            tuple[float, ...]: 固定维度且仅包含有限数值的向量。
        示例:
            示例输入: runtime.embed("Agent memory", 64)
            示例输出: 长度为 64 的向量。
        """
        if dimensions != self.config.embedding_dimensions:
            msg = (
                "embedding dimension request does not match configured dimensions: "
                f"requested={dimensions}, configured={self.config.embedding_dimensions}"
            )
            raise BackendDependencyError(msg)
        if self.provider == "local":
            return embed_text(text, dimensions)
        assert self.gateway is not None
        try:
            values = self.gateway.embed(text)
        except Exception as exc:
            msg = f"embedding gateway request failed: {exc}"
            raise BackendDependencyError(msg) from exc
        return self._validated_vector(values, dimensions)

    def diagnostics(
        self,
        gateway_status: Optional[Mapping[str, Any]] = None,
    ) -> dict:
        """Return the active provider, model, dimension, and health state."""
        if self.provider == "local":
            return {
                "status": "ok",
                "provider": "deterministic_local",
                "model": LOCAL_EMBEDDING_MODEL,
                "dimensions": self.config.embedding_dimensions,
                "vector_dimensions": self.config.embedding_dimensions,
            }
        assert self.gateway is not None
        health = (
            dict(gateway_status)
            if gateway_status is not None
            else self.gateway.healthcheck()
        )
        return {
            "status": health.get("status", "unknown"),
            "provider": "http_gateway",
            "model": self.config.embedding_model or "gateway_default",
            "dimensions": self.config.embedding_dimensions,
            "vector_dimensions": self.config.embedding_dimensions,
            "gateway": health,
        }

    @staticmethod
    def _resolve_provider(config: MemoryConfig) -> str:
        """Resolve auto mode from the selected storage backend."""
        if config.embedding_backend == "auto":
            return "gateway" if config.backend_mode == "production" else "local"
        return config.embedding_backend

    @staticmethod
    def _validated_vector(
        values: Sequence[float],
        dimensions: int,
    ) -> Tuple[float, ...]:
        """Validate gateway output before it can enter an index."""
        try:
            vector = tuple(float(value) for value in values)
        except (TypeError, ValueError) as exc:
            msg = "embedding gateway returned non-numeric values."
            raise BackendDependencyError(msg) from exc
        if len(vector) != dimensions:
            msg = (
                "embedding gateway returned an unexpected vector dimension: "
                f"expected={dimensions}, actual={len(vector)}"
            )
            raise BackendDependencyError(msg)
        if not all(math.isfinite(value) for value in vector):
            msg = "embedding gateway returned non-finite values."
            raise BackendDependencyError(msg)
        return vector
