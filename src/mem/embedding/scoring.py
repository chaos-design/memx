"""Core F1-F5 formulas from the memory design."""

from __future__ import annotations

import math
import re
from typing import Sequence

from ..config.settings import MemoryConfig
from ..memory.models import EpisodicMemory
from .vector import cosine_similarity

# F1 规则信号关键词：显式记忆、约束、偏好、风险和 deadline 都提升重要性。
IMPORTANT_RULE_PATTERN = re.compile(
    r"记住|remember|必须|must|禁止|不要|prefer|偏好|约束|决策|deadline|风险|重要"
)

# F1 规则信号中的数字检测，用于捕获日期、数量、版本等可操作信息。
DIGIT_PATTERN = re.compile(r"\d")

# L4 显著度归一化上界：与 consolidation_strength 的 max_access 同量纲，
# 让「引用数 + 边权之和」贡献落在 [0,1]，衰减项才能保持主导。
SALIENCE_MAX_REF_COUNT = 10


def clip(value: float, lower: int, upper: int) -> int:
    """Clip and round a numeric score.

    输入:
        value: 原始数值。
        lower: 下界。
        upper: 上界。
    输出:
        int: round 后限制在区间内的整数。
    示例:
        示例输入: clip(12.2, 0, 10)
        示例输出: 10
    """
    return max(lower, min(upper, round(value)))


def rule_signal_score(text: str) -> int:
    """Score deterministic importance signals in a text.

    输入:
        text: 待分析文本。
    输出:
        int: 0-10 的规则分数。
    示例:
        示例输入: rule_signal_score("请记住这个约束")
        示例输出: 5
    """
    score = 0
    if IMPORTANT_RULE_PATTERN.search(text):
        score += 5
    if DIGIT_PATTERN.search(text):
        score += 2
    if "!" in text or "！" in text:
        score += 1
    if len(text) > 120:
        score += 2
    return min(score, 10)


def user_emphasis_score(text: str) -> int:
    """Score explicit user emphasis signals.

    输入:
        text: 用户文本。
    输出:
        int: 0-10 的显式强调分数。
    示例:
        示例输入: user_emphasis_score("务必记住")
        示例输出: 7
    """
    lowered = text.lower()
    score = 0
    if "记住" in text or "remember" in lowered:
        score += 7
    if "重要" in text or "important" in lowered:
        score += 2
    if "必须" in text or "must" in lowered:
        score += 1
    return min(score, 10)


def f1_importance(s_llm: float, s_rule: float, s_user: float) -> int:
    """Compute F1 memory importance.

    输入:
        s_llm: LLM 打分，0-10。
        s_rule: 规则信号分，0-10。
        s_user: 用户强调分，0-10。
    输出:
        int: importance，范围 0-10。
    示例:
        示例输入: f1_importance(8, 6, 10)
        示例输出: 8
    """
    return clip(0.4 * s_llm + 0.3 * s_rule + 0.3 * s_user, 0, 10)


def f2_score(
    memory: EpisodicMemory,
    query_embedding: Sequence[float],
    now_ts: float,
    config: MemoryConfig,
) -> float:
    """Compute F2 retrieval score for an L2 memory.

    输入:
        memory: L2 记忆对象。
        query_embedding: query 向量。
        now_ts: 当前时间戳。
        config: 配置对象。
    输出:
        float: 综合检索分。
    示例:
        示例输入: f2_score(memory, query_embedding, 1000.0, MemoryConfig())
        示例输出: 0.0 到 1.0 附近的综合排序分。
    """
    relevance = cosine_similarity(query_embedding, memory.embedding)
    elapsed_hours = max(0.0, now_ts - memory.ts_last_access) / 3_600.0
    recency = config.recency_decay_per_hour**elapsed_hours
    importance = memory.importance / 10.0
    return (
        config.f2_weight_relevance * relevance
        + config.f2_weight_recency * recency
        + config.f2_weight_importance * importance
    )


def f3_retention(memory: EpisodicMemory, now_ts: float) -> float:
    """Compute F3 Ebbinghaus retention.

    输入:
        memory: L2 记忆对象。
        now_ts: 当前时间戳。
    输出:
        float: 保持率，范围 0-1。
    示例:
        示例输入: f3_retention(memory, memory.ts_last_access)
        示例输出: 1.0
    """
    elapsed = max(0.0, now_ts - memory.ts_last_access)
    return math.exp(-elapsed / memory.stability)


def f4_forget_score(memory: EpisodicMemory, now_ts: float) -> float:
    """Compute F4 forgetting score.

    输入:
        memory: L2 记忆对象。
        now_ts: 当前时间戳。
    输出:
        float: 综合遗忘分，越小越应遗忘。
    示例:
        示例输入: f4_forget_score(memory, memory.ts_last_access)
        示例输出: 依赖 access_count 的非负浮点数。
    """
    importance_factor = 0.5 + 0.5 * (memory.importance / 10.0)
    access_factor = math.log(1 + memory.access_count) + 1
    return f3_retention(memory, now_ts) * importance_factor * access_factor


def stability_after_reinforce(current_stability: float, gamma: float) -> float:
    """Compute reinforced stability.

    输入:
        current_stability: 当前稳定度。
        gamma: reinforce 增益。
    输出:
        float: 增强后的稳定度。
    示例:
        示例输入: stability_after_reinforce(86400, 1.5)
        示例输出: 129600.0
    """
    return current_stability * gamma


def initial_stability(importance: int, config: MemoryConfig) -> float:
    """Compute initial stability with importance adjustment.

    输入:
        importance: F1 输出的重要性，0-10。
        config: 配置对象。
    输出:
        float: 初始稳定度。
    示例:
        示例输入: initial_stability(8, MemoryConfig())
        示例输出: 120960.0
    """
    return config.initial_stability_seconds * (
        1 + config.stability_importance_lambda * importance / 10.0
    )


def consolidation_strength(
    importance: int,
    access_count: int,
    density: float,
    max_access: int = 10,
) -> float:
    """Compute the consolidation strength C(m).

    输入:
        importance: 记忆重要性。
        access_count: 命中次数。
        density: 图或向量邻域密度，0-1。
        max_access: 访问次数归一化上界。
    输出:
        float: 巩固强度。
    示例:
        示例输入: consolidation_strength(8, 3, 0.5)
        示例输出: 0.0 到 1.0 附近的巩固强度分。
    """
    if max_access <= 0:
        msg = "max_access must be positive."
        raise ValueError(msg)
    access_term = math.log(1 + access_count) / math.log(1 + max_access)
    return 0.4 * (importance / 10.0) + 0.3 * access_term + 0.3 * density


def salience_update(
    current_salience: float,
    ref_count: int,
    edge_weight_sum: float,
    decay: float,
    max_ref_count: int = SALIENCE_MAX_REF_COUNT,
) -> float:
    """Compute L4 node salience update.

    输入:
        current_salience: 当前显著度。
        ref_count: 引用次数。
        edge_weight_sum: 关联边权重和。
        decay: 衰减系数 μ。
        max_ref_count: 引用次数归一化上界。
    输出:
        float: 限制在 0-1 的新显著度。
    示例:
        示例输入: salience_update(0.5, 2, 0.3, 0.8)
        示例输出: 0.5
    """
    if max_ref_count <= 0:
        msg = "max_ref_count must be positive."
        raise ValueError(msg)
    # 设计文档 §5.4 要求对 (ref_count + Σweight) 做归一化后再进入 EMA。
    # 归一化不可省：ref_count 无上界，直接相加会让加性项支配衰减项，
    # 使 s' 恒 ≥ s，prune 的衰减语义退化为单调递增。
    support = min(ref_count, max_ref_count) / max_ref_count
    reinforcement = min(1.0, support + max(0.0, edge_weight_sum))
    raw = decay * current_salience + (1 - decay) * reinforcement
    return max(0.0, min(1.0, raw))
