"""Configuration center for the Agent memory system."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Optional, Tuple

from .paths import DEFAULT_MEMORY_DIR, validate_memory_dir


@dataclass(frozen=True)
class MemoryConfig:
    """Centralized parameters for all memory layers and formulas."""

    # 后端模式：memory 使用本地内存 Adapter；production 使用外部依赖 Adapter。
    backend_mode: str = "memory"

    # 写链路是否同步持久化整作用域快照；生产模式建议关闭并改由后台 flush。
    persist_on_write: bool = True

    # 生产 Redis URL，用于 L0 缓冲与 inbox 队列 Adapter。
    redis_url: Optional[str] = None

    # 生产 PostgreSQL DSN，用于 L2/L3 权威表与 pgvector Adapter。
    postgres_dsn: Optional[str] = None

    # 生产 Neo4j URI，用于 L4 图谱 Adapter。
    neo4j_uri: Optional[str] = None

    # 生产 Neo4j 用户名。
    neo4j_user: Optional[str] = None

    # 生产 Neo4j 密码。
    neo4j_password: Optional[str] = None

    # 生产 LLM Gateway 地址，用于固化决策与 embedding 统一出口。
    llm_gateway_url: Optional[str] = None

    # 生产 LLM Gateway 鉴权 token。
    llm_api_key: Optional[str] = None

    # 生产后端连接超时秒数。
    backend_connection_timeout_seconds: float = 3.0

    # L0 token 占 L1 工作记忆容量的比例阈值，超过后触发压缩。
    theta_ctx_ratio: float = 0.60

    # L0 累积写入轮数触发阈值，每 N 轮将原始对话压缩进 L1。
    flush_turns: int = 8

    # L1 工作记忆的目标 token 容量，用于控制滚动摘要长度。
    working_memory_tokens: int = 2_000

    # L2 active 记忆 importance 总和达到该阈值后允许 reflect 到 L3/L4。
    reflect_importance_threshold: int = 150

    # L2 每个作用域 active 情景记忆的容量上限。
    episodic_capacity: int = 100_000

    # L2 动态遗忘的基础阈值，低于阈值的低重要性记忆会被归档。
    forget_threshold: float = 0.15

    # 新写入 L2 记忆的保护窗口，窗口内不参与 active -> archived 遗忘。
    new_memory_grace_seconds: float = 86_400.0

    # L3 事实写入的最低置信度，低于该值直接拒绝。
    confidence_threshold: float = 0.30

    # F2 近因分每小时衰减系数，越接近 1 表示新旧记忆差异越小。
    recency_decay_per_hour: float = 0.99

    # F3 遗忘曲线的初始稳定度秒数，作为新记忆 retention 的时间尺度。
    initial_stability_seconds: float = 86_400.0

    # F4 reinforce 后稳定度放大倍数，用于提升被成功召回记忆的保留概率。
    reinforce_gamma: float = 1.50

    # F2 检索重排的语义相关性权重。
    f2_weight_relevance: float = 0.55

    # F2 检索重排的近因性权重。
    f2_weight_recency: float = 0.20

    # F2 检索重排的重要性权重。
    f2_weight_importance: float = 0.25

    # RRF 融合的平滑常量，值越大多路排名差异越平滑。
    rrf_k0: int = 60

    # 动态遗忘压力增益，占用率超过 baseline 时提高遗忘阈值。
    pressure_kappa: float = 0.50

    # L2 容量压力基线，超过后开始增强遗忘压力。
    occupancy_baseline: float = 0.80

    # 初始稳定度的重要性加成系数，高 importance 记忆天然更抗遗忘。
    stability_importance_lambda: float = 0.50

    # L0 原始消息环形窗口容量，仅保留最近 N 轮。
    raw_window_turns: int = 32

    # L0 原始消息 TTL 秒数，超时消息会被淘汰并补偿压缩到 L1。
    raw_ttl_seconds: float = 3_600.0

    # recall/search 的统一返回上限，防止调用方放大关键路径成本。
    max_recall_k: int = 50

    # L4 图节点显著度维护的衰减系数。
    graph_salience_decay: float = 0.80

    # L4 孤立低显著节点剪枝阈值。
    graph_prune_threshold: float = 0.05

    # 巩固阶段相似事件的合并阈值，预留给后续压缩/去重策略。
    similarity_merge_threshold: float = 0.92

    # 本地 deterministic embedding 维度；生产环境可替换为真实模型维度。
    embedding_dimensions: int = 64

    # L3 冲突治理中“近似同置信度”的容忍区间。
    conflict_confidence_epsilon: float = 0.05

    # L3 冲突治理中“明确置信差”的替换/保留门槛。
    conflict_confidence_gap: float = 0.20

    # L2 检索候选倍数，限制进入 RRF/F2 重排的候选规模。
    retrieval_candidate_multiplier: int = 2

    # L2 单次检索候选硬上限，避免无 sparse 命中时扫描整作用域热区。
    retrieval_candidate_hard_limit: int = 1_000

    # L2 检索最低语义相关度，低于该值且无关键词命中的候选会被过滤。
    minimum_relevance_score: float = 0.05

    # ConsolidationAgent 每次处理 inbox 的最大批量。
    consolidation_batch_size: int = 50

    # inbox 单条固化任务最大重试次数。
    inbox_max_retries: int = 3

    # recall 是否同步持久化整作用域快照；默认关闭以保护关键路径。
    persist_on_recall: bool = False

    # L2 证据被归档/删除后，对唯一证据事实执行的置信度惩罚。
    orphan_evidence_confidence_penalty: float = 0.10

    # 时序型事实 key：同 key 新旧值变化应归档旧版本，而非当作错误删除。
    temporal_fact_keys: Tuple[str, ...] = (
        "device.os",
        "location.city",
        "job.title",
    )

    # Memory 数据持久化目录，必须是项目根目录下 .memories 的相对路径。
    memory_dir: str = DEFAULT_MEMORY_DIR

    def __post_init__(self) -> None:
        """Validate config boundaries.

        输入:
            self: 配置对象。
        输出:
            None；非法配置会抛出 ValueError。
        示例:
            示例输入: MemoryConfig(max_recall_k=10)
            示例输出: MemoryConfig 对象完成初始化，无异常。
        """
        if self.backend_mode not in {"memory", "production"}:
            msg = "backend_mode must be 'memory' or 'production'."
            raise ValueError(msg)
        if self.backend_connection_timeout_seconds <= 0:
            msg = "backend_connection_timeout_seconds must be positive."
            raise ValueError(msg)
        if not 0 < self.theta_ctx_ratio <= 1:
            msg = "theta_ctx_ratio must be in (0, 1]."
            raise ValueError(msg)
        if self.flush_turns <= 0:
            msg = "flush_turns must be positive."
            raise ValueError(msg)
        if self.working_memory_tokens <= 0:
            msg = "working_memory_tokens must be positive."
            raise ValueError(msg)
        if self.episodic_capacity <= 0:
            msg = "episodic_capacity must be positive."
            raise ValueError(msg)
        if self.new_memory_grace_seconds < 0:
            msg = "new_memory_grace_seconds must be non-negative."
            raise ValueError(msg)
        if self.initial_stability_seconds <= 0:
            msg = "initial_stability_seconds must be positive."
            raise ValueError(msg)
        if self.max_recall_k <= 0:
            msg = "max_recall_k must be positive."
            raise ValueError(msg)
        if self.embedding_dimensions <= 0:
            msg = "embedding_dimensions must be positive."
            raise ValueError(msg)
        if self.conflict_confidence_gap < 0:
            msg = "conflict_confidence_gap must be non-negative."
            raise ValueError(msg)
        if self.retrieval_candidate_multiplier <= 0:
            msg = "retrieval_candidate_multiplier must be positive."
            raise ValueError(msg)
        if self.retrieval_candidate_hard_limit <= 0:
            msg = "retrieval_candidate_hard_limit must be positive."
            raise ValueError(msg)
        if self.minimum_relevance_score < 0:
            msg = "minimum_relevance_score must be non-negative."
            raise ValueError(msg)
        if self.consolidation_batch_size <= 0:
            msg = "consolidation_batch_size must be positive."
            raise ValueError(msg)
        if self.inbox_max_retries <= 0:
            msg = "inbox_max_retries must be positive."
            raise ValueError(msg)
        if not 0 <= self.orphan_evidence_confidence_penalty <= 1:
            msg = "orphan_evidence_confidence_penalty must be in [0, 1]."
            raise ValueError(msg)
        validate_memory_dir(self.memory_dir)

    def with_overrides(self, **kwargs: object) -> "MemoryConfig":
        """Create a validated copy with changed fields.

        输入:
            **kwargs: 需要覆盖的配置字段。
        输出:
            MemoryConfig: 新配置对象。
        示例:
            示例输入: MemoryConfig().with_overrides(flush_turns=1)
            示例输出: MemoryConfig(flush_turns=1, ...)
        """
        return replace(self, **kwargs)

    def production_dependencies(self) -> Dict[str, Optional[str]]:
        """Return production backend dependency settings.

        输入:
            self: 配置对象。
        输出:
            dict: Redis、PostgreSQL、Neo4j 与 LLM Gateway 连接配置。
        示例:
            示例输入: MemoryConfig(redis_url="redis://localhost").production_dependencies()
            示例输出: {"redis_url": "redis://localhost", ...}
        """
        return {
            "redis_url": self.redis_url,
            "postgres_dsn": self.postgres_dsn,
            "neo4j_uri": self.neo4j_uri,
            "neo4j_user": self.neo4j_user,
            "neo4j_password": self.neo4j_password,
            "llm_gateway_url": self.llm_gateway_url,
            "llm_api_key": self.llm_api_key,
        }

    def dynamic_forget_threshold(self, occupancy: float) -> float:
        """Compute the adaptive forgetting threshold.

        输入:
            occupancy: L2 当前占用率，范围通常为 0 到 1。
        输出:
            float: 动态遗忘阈值。
        示例:
            示例输入: MemoryConfig().dynamic_forget_threshold(0.9)
            示例输出: 0.1575
        """
        pressure = 1 + self.pressure_kappa * (occupancy - self.occupancy_baseline)
        return max(0.0, self.forget_threshold * pressure)

    @property
    def compression_token_threshold(self) -> int:
        """Return the L0 to L1 compression trigger in tokens.

        输入:
            self: 配置对象。
        输出:
            int: 触发压缩的 token 估算阈值。
        示例:
            示例输入:
                MemoryConfig(working_memory_tokens=100).compression_token_threshold
            示例输出: 60
        """
        return int(self.working_memory_tokens * self.theta_ctx_ratio)
