"""Hybrid dense/sparse retrieval coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Set, Tuple

from ..config.settings import MemoryConfig
from ..embedding.vector import cosine_similarity, tokenize
from ..memory.models import EpisodicMemory
from .candidate_pool import build_candidate_pool
from .diagnostics import retrieval_stats
from .ranking import (
    dense_rank,
    filter_scored_candidates,
    keyword_overlap_tokens,
    rerank_final,
    rrf_merge,
    sparse_rank,
)

Embedder = Callable[[str, int], Tuple[float, ...]]


@dataclass(frozen=True)
class RetrievalOutcome:
    """Hybrid retrieval results and diagnostics."""

    memories: List[EpisodicMemory]
    stats: Dict[str, object]
    candidate_source: str


def hybrid_retrieve(
    query: str,
    scope_id: str,
    k: int,
    now_ts: float,
    include_archived: bool,
    config: MemoryConfig,
    embedder: Embedder,
    records: Mapping[str, EpisodicMemory],
    token_index: Mapping[str, frozenset],
    inverted_index: Mapping[str, Set[str]],
) -> RetrievalOutcome:
    """Retrieve L2 memories with dense/sparse fusion and final F2 rerank.

    输入:
        query: 检索语句。
        scope_id: 作用域 ID。
        k: 返回数量。
        now_ts: 当前时间戳。
        include_archived: 是否包含 archived。
        config: 系统配置。
        embedder: 文本向量化函数。
        records: 当前作用域 L2 记录。
        token_index: 当前作用域 mem_id 到 token 集合映射。
        inverted_index: 当前作用域倒排索引。
    输出:
        RetrievalOutcome: 排序结果和检索诊断。
    示例:
        示例输入: hybrid_retrieve("memory", "scope", 5, 1.0, False, ...)
        示例输出: RetrievalOutcome(memories=[...], stats={...}, candidate_source="...")
    """
    if k <= 0:
        return RetrievalOutcome([], {}, "none")
    query_embedding = embedder(query, config.embedding_dimensions)
    query_tokens = frozenset(tokenize(query))
    pool = build_candidate_pool(
        records=records,
        query_tokens=query_tokens,
        inverted_index=inverted_index,
        config=config,
        include_archived=include_archived,
        k=k,
    )
    scored_candidates = filter_scored_candidates(
        (
            (
                memory,
                cosine_similarity(query_embedding, memory.embedding),
                keyword_overlap_tokens(
                    query_tokens,
                    token_index.get(memory.mem_id, frozenset()),
                ),
            )
            for memory in pool.candidates
        ),
        config.minimum_relevance_score,
    )
    if not scored_candidates:
        stats = retrieval_stats(
            scope_id=scope_id,
            query_tokens=query_tokens,
            candidate_count=len(pool.candidates),
            filtered_count=0,
            dense_ranked=0,
            sparse_ranked=0,
            candidate_source=pool.source,
            candidate_limit=config.retrieval_candidate_hard_limit,
        )
        return RetrievalOutcome([], stats, pool.source)
    candidate_limit = min(
        len(scored_candidates),
        max(k, k * config.retrieval_candidate_multiplier),
    )
    dense_ranked = dense_rank(scored_candidates, candidate_limit)
    sparse_ranked = sparse_rank(scored_candidates, candidate_limit)
    stats = retrieval_stats(
        scope_id=scope_id,
        query_tokens=query_tokens,
        candidate_count=len(pool.candidates),
        filtered_count=len(scored_candidates),
        dense_ranked=len(dense_ranked),
        sparse_ranked=len(sparse_ranked),
        candidate_source=pool.source,
        candidate_limit=config.retrieval_candidate_hard_limit,
    )
    fused = rrf_merge([dense_ranked, sparse_ranked], config.rrf_k0)
    if not fused:
        fused = [item[0] for item in scored_candidates]
    memories = rerank_final(fused, query_embedding, now_ts, config, k)
    return RetrievalOutcome(memories, stats, pool.source)
