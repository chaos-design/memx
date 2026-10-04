"""Retrieval diagnostics helpers."""

from __future__ import annotations

from typing import Dict, Iterable

from ..constants import (
    RETRIEVAL_STAT_CANDIDATE_COUNT,
    RETRIEVAL_STAT_CANDIDATE_LIMIT,
    RETRIEVAL_STAT_CANDIDATE_SOURCE,
    RETRIEVAL_STAT_DENSE_RANKED,
    RETRIEVAL_STAT_FILTERED_COUNT,
    RETRIEVAL_STAT_QUERY_TOKENS,
    RETRIEVAL_STAT_SCOPE_ID,
    RETRIEVAL_STAT_SPARSE_RANKED,
)


def retrieval_stats(
    scope_id: str,
    query_tokens: Iterable[str],
    candidate_count: int,
    filtered_count: int,
    dense_ranked: int,
    sparse_ranked: int,
    candidate_source: str,
    candidate_limit: int,
) -> Dict[str, object]:
    """Build retrieval diagnostics for architecture snapshots.

    输入:
        scope_id: 作用域 ID。
        query_tokens: 查询 token。
        candidate_count: 原始候选数量。
        filtered_count: 过滤后候选数量。
        dense_ranked: dense 排序数量。
        sparse_ranked: sparse 排序数量。
        candidate_source: 候选池来源。
        candidate_limit: 候选硬上限。
    输出:
        dict: 诊断统计。
    示例:
        示例输入: retrieval_stats("scope", ["a"], 1, 1, 1, 1, "source", 1000)
        示例输出: {"scope_id": "scope", "candidate_count": 1, ...}
    """
    return {
        RETRIEVAL_STAT_SCOPE_ID: scope_id,
        RETRIEVAL_STAT_QUERY_TOKENS: sorted(query_tokens),
        RETRIEVAL_STAT_CANDIDATE_COUNT: candidate_count,
        RETRIEVAL_STAT_FILTERED_COUNT: filtered_count,
        RETRIEVAL_STAT_DENSE_RANKED: dense_ranked,
        RETRIEVAL_STAT_SPARSE_RANKED: sparse_ranked,
        RETRIEVAL_STAT_CANDIDATE_SOURCE: candidate_source,
        RETRIEVAL_STAT_CANDIDATE_LIMIT: candidate_limit,
    }
