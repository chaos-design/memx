"""Ranking helpers for hybrid retrieval."""

from __future__ import annotations

from collections import defaultdict
from heapq import nlargest
from typing import Dict, Iterable, List, Tuple

from ..config.settings import MemoryConfig
from ..embedding.scoring import f2_score
from ..memory.models import EpisodicMemory

ScoredCandidate = Tuple[EpisodicMemory, float, int]


def keyword_overlap_tokens(
    query_tokens: frozenset,
    memory_tokens: frozenset,
) -> int:
    """Compute sparse keyword overlap from token sets.

    输入:
        query_tokens: 查询 token 集合。
        memory_tokens: 记忆 token 集合。
    输出:
        int: token 交集数量。
    示例:
        示例输入: keyword_overlap_tokens(frozenset({"a"}), frozenset({"a", "b"}))
        示例输出: 1
    """
    return len(query_tokens & memory_tokens)


def hot_candidate_score(memory: EpisodicMemory) -> Tuple[int, int, float]:
    """Score fallback candidates by operational heat.

    输入:
        memory: L2 记忆对象。
    输出:
        tuple: importance、access_count、ts_last_access 组成的排序键。
    示例:
        示例输入: hot_candidate_score(memory)
        示例输出: (8, 3, 1719000000.0)
    """
    return (memory.importance, memory.access_count, memory.ts_last_access)


def filter_scored_candidates(
    scored_candidates: Iterable[ScoredCandidate],
    minimum_relevance_score: float,
) -> List[ScoredCandidate]:
    """Filter candidates by dense relevance or sparse overlap.

    输入:
        scored_candidates: 带 dense/sparse 分数的候选。
        minimum_relevance_score: 最低 dense 相关度。
    输出:
        list[ScoredCandidate]: 过滤后的候选。
    示例:
        示例输入: filter_scored_candidates([(memory, 0.1, 0)], 0.05)
        示例输出: [(memory, 0.1, 0)]
    """
    return [
        item
        for item in scored_candidates
        if item[1] >= minimum_relevance_score or item[2] > 0
    ]


def dense_rank(
    scored_candidates: List[ScoredCandidate],
    limit: int,
) -> List[EpisodicMemory]:
    """Rank candidates by dense similarity.

    输入:
        scored_candidates: 带 dense/sparse 分数的候选。
        limit: 最大返回数量。
    输出:
        list[EpisodicMemory]: dense 排序结果。
    示例:
        示例输入: dense_rank([(memory, 0.5, 1)], 1)
        示例输出: [memory]
    """
    return [
        item[0]
        for item in nlargest(limit, scored_candidates, key=lambda item: item[1])
    ]


def sparse_rank(
    scored_candidates: List[ScoredCandidate],
    limit: int,
) -> List[EpisodicMemory]:
    """Rank candidates by sparse keyword overlap.

    输入:
        scored_candidates: 带 dense/sparse 分数的候选。
        limit: 最大返回数量。
    输出:
        list[EpisodicMemory]: sparse 排序结果。
    示例:
        示例输入: sparse_rank([(memory, 0.5, 1)], 1)
        示例输出: [memory]
    """
    return [
        item[0]
        for item in nlargest(limit, scored_candidates, key=lambda item: item[2])
        if item[2] > 0
    ]


def rrf_merge(
    rankings: List[List[EpisodicMemory]],
    rrf_k0: int,
) -> List[EpisodicMemory]:
    """Fuse rankings with reciprocal-rank fusion.

    输入:
        rankings: 多路排序结果。
        rrf_k0: RRF 平滑常量。
    输出:
        list[EpisodicMemory]: RRF 融合后的结果。
    示例:
        示例输入: rrf_merge([[memory]], 60)
        示例输出: [memory]
    """
    scores: Dict[str, float] = defaultdict(float)
    by_id: Dict[str, EpisodicMemory] = {}
    for ranking in rankings:
        for index, memory in enumerate(ranking):
            by_id[memory.mem_id] = memory
            scores[memory.mem_id] += 1 / (rrf_k0 + index + 1)
    return sorted(by_id.values(), key=lambda item: scores[item.mem_id], reverse=True)


def rerank_final(
    candidates: List[EpisodicMemory],
    query_embedding: Tuple[float, ...],
    now_ts: float,
    config: MemoryConfig,
    k: int,
) -> List[EpisodicMemory]:
    """Apply final F2 ranking to fused candidates.

    输入:
        candidates: RRF 融合后的候选。
        query_embedding: 查询向量。
        now_ts: 当前时间戳。
        config: 系统配置。
        k: 最大返回数量。
    输出:
        list[EpisodicMemory]: 最终排序结果。
    示例:
        示例输入: rerank_final([memory], (0.1, ...), 1.0, config, 1)
        示例输出: [memory]
    """
    return nlargest(
        k,
        candidates,
        key=lambda item: f2_score(item, query_embedding, now_ts, config),
    )
