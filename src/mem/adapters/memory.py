"""Adapter assembly for Agent memory backend ports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config.settings import MemoryConfig
from ..embedding.provider import EmbeddingRuntime
from ..embedding.vector import embed_text
from ..graph.cognitive import CognitiveGraph
from ..ingest.buffer import ConversationBuffer
from ..ingest.inbox import InMemoryInbox
from ..ingest.working import WorkingMemoryManager
from ..memory.episodic import EpisodicStore
from ..memory.ports import (
    InboxPort,
    L0BufferPort,
    L1WorkingMemoryPort,
    L2EpisodicPort,
    L3SemanticPort,
    L4GraphPort,
    LLMGatewayPort,
    SnapshotStorePort,
)
from ..memory.semantic import SemanticStore
from ..persistence.storage import MemoryFileStore


class NoopLLMGateway:
    """Deterministic local LLM gateway used by tests and memory mode."""

    def __init__(self, config: MemoryConfig) -> None:
        """Initialize the deterministic gateway.

        输入:
            config: 记忆系统配置。
        输出:
            None。
        示例:
            示例输入: NoopLLMGateway(MemoryConfig())
            示例输出: NoopLLMGateway 实例可执行 embed 与 decide_json。
        """
        self.config = config

    def decide_json(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Return a conservative local decision.

        输入:
            prompt: 决策提示词。
            schema: JSON Schema。
        输出:
            dict: 固定 skip 决策。
        示例:
            示例输入: gateway.decide_json("classify", {"type": "object"})
            示例输出: {"op": "skip", "reason": "noop_gateway"}
        """
        return {
            "op": "skip",
            "reason": "noop_gateway",
            "prompt_size": len(prompt),
            "schema_keys": sorted(schema),
        }

    def embed(self, text: str) -> List[float]:
        """Return deterministic local embeddings.

        输入:
            text: 待向量化文本。
        输出:
            list[float]: deterministic embedding。
        示例:
            示例输入: gateway.embed("Agent memory")
            示例输出: [0.0, ...]，长度等于配置维度。
        """
        return list(embed_text(text, self.config.embedding_dimensions))

    def healthcheck(self) -> Dict[str, Any]:
        """Return local gateway diagnostics.

        输入:
            self: NoopLLMGateway 实例。
        输出:
            dict: 健康状态。
        示例:
            示例输入: gateway.healthcheck()
            示例输出: {"status": "ok", "mode": "noop"}
        """
        return {
            "status": "ok",
            "mode": "noop",
            "embedding_dimensions": self.config.embedding_dimensions,
        }


@dataclass
class MemoryBackendBundle:
    """Concrete adapters used by AgentMemory."""

    l0: L0BufferPort
    l1: L1WorkingMemoryPort
    l2: L2EpisodicPort
    l3: L3SemanticPort
    l4: L4GraphPort
    inbox: InboxPort
    storage: SnapshotStorePort
    llm_gateway: LLMGatewayPort
    embedding_runtime: EmbeddingRuntime
    profile: str = "memory"
    external_services: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def in_memory(
        cls,
        config: MemoryConfig,
        llm_gateway: Optional[LLMGatewayPort] = None,
    ) -> "MemoryBackendBundle":
        """Build the default in-memory backend bundle.

        输入:
            config: 记忆系统配置。
            llm_gateway: 可选 HTTP Gateway，用于本地存储配合远程 embedding。
        输出:
            MemoryBackendBundle: 内存 Adapter 组合。
        示例:
            示例输入: MemoryBackendBundle.in_memory(MemoryConfig())
            示例输出: profile="memory" 的后端组合。
        """
        gateway = llm_gateway or NoopLLMGateway(config)
        embedding_runtime = EmbeddingRuntime(config, gateway=gateway)
        return cls(
            l0=ConversationBuffer(config),
            l1=WorkingMemoryManager(config),
            l2=EpisodicStore(config, embedder=embedding_runtime.embed),
            l3=SemanticStore(config, embedder=embedding_runtime.embed),
            l4=CognitiveGraph(config),
            inbox=InMemoryInbox(max_retries=config.inbox_max_retries),
            storage=MemoryFileStore(config.memory_dir),
            llm_gateway=gateway,
            embedding_runtime=embedding_runtime,
            profile="memory",
            external_services={"local_snapshot": config.memory_dir},
        )

    def diagnostics(self) -> Dict[str, Any]:
        """Return backend composition diagnostics.

        输入:
            self: MemoryBackendBundle 实例。
        输出:
            dict: 当前 Adapter 类型与外部服务摘要。
        示例:
            示例输入: bundle.diagnostics()
            示例输出: {"profile": "memory", "adapters": {...}}
        """
        gateway_status = self.llm_gateway.healthcheck()
        return {
            "profile": self.profile,
            "adapters": {
                "l0": type(self.l0).__name__,
                "l1": type(self.l1).__name__,
                "l2": type(self.l2).__name__,
                "l3": type(self.l3).__name__,
                "l4": type(self.l4).__name__,
                "inbox": type(self.inbox).__name__,
                "storage": type(self.storage).__name__,
                "llm_gateway": type(self.llm_gateway).__name__,
            },
            "external_services": dict(self.external_services),
            "llm_gateway": gateway_status,
            "embedding": self.embedding_runtime.diagnostics(gateway_status),
        }


def build_memory_backend(config: MemoryConfig) -> MemoryBackendBundle:
    """Build adapters according to MemoryConfig.backend_mode.

    输入:
        config: 记忆系统配置。
    输出:
        MemoryBackendBundle: 可注入 AgentMemory 的后端组合。
    示例:
        示例输入: build_memory_backend(MemoryConfig())
        示例输出: MemoryBackendBundle(profile="memory", ...)
    """
    if config.backend_mode == "memory":
        gateway = None
        if config.embedding_backend == "gateway":
            from .production import HttpLLMGateway

            gateway = HttpLLMGateway(config)
        return MemoryBackendBundle.in_memory(config, llm_gateway=gateway)
    from .production import build_production_backend

    return build_production_backend(config)
