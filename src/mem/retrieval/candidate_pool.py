"""Candidate pool construction for hybrid retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from heapq import nlargest
from typing import Iterable, List, Mapping, Set

from ..config.settings import MemoryConfig
from ..constants import (
    RETRIEVAL_SOURCE_EMPTY_QUERY_HOT_FALLBACK,
    RETRIEVAL_SOURCE_NO_SPARSE_MATCH_HOT_FALLBACK,
    RETRIEVAL_SOURCE_SPARSE_ONLY_BOUNDED,
    RETRIEVAL_SOURCE_SPARSE_PLUS_HOT_FALLBACK,
)
from ..memory.models import EpisodicMemory, MemoryStatus
from .ranking import hot_candidate_score


@dataclass(frozen=True)
class CandidatePoolResult:
    """Result from retrieval candidate selection."""

    candidates: List[EpisodicMemory]
    source: str


def retrievable_candidates(
    records: Mapping[str, EpisodicMemory],
    include_archived: bool,
) -> List[EpisodicMemory]:
    """Return records eligible for retrieval.

    输入:
        records: mem_id 到 EpisodicMemory 的映射。
        include_archived: 是否包含 archived 记忆。
    输出:
        list[EpisodicMemory]: 可检索候选。
    示例:
        示例输入: retrievable_candidates({"m1": memory}, False)
        示例输出: [memory]
    """
    statuses = {MemoryStatus.ACTIVE}
    if include_archived:
        statuses.add(MemoryStatus.ARCHIVED)
    return [record for record in records.values() if record.status in statuses]


def bounded_hot_candidates(
    candidates: List[EpisodicMemory],
    k: int,
    hard_limit: int,
) -> List[EpisodicMemory]:
    """Return a hot bounded fallback candidate pool.

    输入:
        candidates: 可检索候选列表。
        k: 请求返回数量。
        hard_limit: 候选硬上限。
    输出:
        list[EpisodicMemory]: 不超过硬上限的热点候选。
    示例:
        示例输入: bounded_hot_candidates([memory], 8, 1000)
        示例输出: [memory]
    """
    limit = min(len(candidates), max(k, hard_limit))
    if len(candidates) <= limit:
        return candidates
    return nlargest(limit, candidates, key=hot_candidate_score)


def build_candidate_pool(
    records: Mapping[str, EpisodicMemory],
    query_tokens: frozenset,
    inverted_index: Mapping[str, Set[str]],
    config: MemoryConfig,
    include_archived: bool,
    k: int,
) -> CandidatePoolResult:
    """Build a bounded retrieval candidate pool.

    输入:
        records: 当前作用域 L2 记录。
        query_tokens: 查询 token 集合。
        inverted_index: 当前作用域倒排索引。
        config: 系统配置。
        include_archived: 是否包含 archived。
        k: 请求返回数量。
    输出:
        CandidatePoolResult: 候选列表及来源。
    示例:
        示例输入: build_candidate_pool(records, tokens, index, config, False, 8)
        示例输出: CandidatePoolResult(candidates=[...], source="...")
    """
    all_candidates = retrievable_candidates(records, include_archived)
    if not query_tokens:
        return CandidatePoolResult(
            bounded_hot_candidates(
                all_candidates,
                k,
                config.retrieval_candidate_hard_limit,
            ),
            RETRIEVAL_SOURCE_EMPTY_QUERY_HOT_FALLBACK,
        )
    matched_ids = _matched_ids(query_tokens, inverted_index)
    if not matched_ids:
        return CandidatePoolResult(
            bounded_hot_candidates(
                all_candidates,
                k,
                config.retrieval_candidate_hard_limit,
            ),
            RETRIEVAL_SOURCE_NO_SPARSE_MATCH_HOT_FALLBACK,
        )
    return _sparse_candidate_pool(all_candidates, matched_ids, config, k)


def _matched_ids(
    query_tokens: Iterable[str],
    inverted_index: Mapping[str, Set[str]],
) -> Set[str]:
    """Collect sparse matches from an inverted index.

    输入:
        query_tokens: 查询 token。
        inverted_index: token 到 mem_id 集合的映射。
    输出:
        set[str]: 命中的 mem_id。
    示例:
        示例输入: _matched_ids(["a"], {"a": {"m1"}})
        示例输出: {"m1"}
    """
    matched_ids: Set[str] = set()
    for token in query_tokens:
        matched_ids.update(inverted_index.get(token, set()))
    return matched_ids


def _sparse_candidate_pool(
    all_candidates: List[EpisodicMemory],
    matched_ids: Set[str],
    config: MemoryConfig,
    k: int,
) -> CandidatePoolResult:
    """Build a sparse-first candidate pool with hot fallback.

    输入:
        all_candidates: 所有可检索候选。
        matched_ids: sparse 命中的 mem_id。
        config: 系统配置。
        k: 请求返回数量。
    输出:
        CandidatePoolResult: 候选池及来源。
    示例:
        示例输入: _sparse_candidate_pool([memory], {"m1"}, config, 8)
        示例输出: CandidatePoolResult(candidates=[memory], source="...")
    """
    by_id = {memory.mem_id: memory for memory in all_candidates}
    matched = [by_id[mem_id] for mem_id in matched_ids if mem_id in by_id]
    candidate_limit = max(
        k,
        min(
            k * config.retrieval_candidate_multiplier * 4,
            config.retrieval_candidate_hard_limit,
        ),
    )
    if len(matched) >= candidate_limit:
        return CandidatePoolResult(
            nlargest(candidate_limit, matched, key=hot_candidate_score),
            RETRIEVAL_SOURCE_SPARSE_ONLY_BOUNDED,
        )
    matched_set = {memory.mem_id for memory in matched}
    fallback = [memory for memory in all_candidates if memory.mem_id not in matched_set]
    fallback_limit = max(0, candidate_limit - len(matched))
    if fallback_limit:
        matched.extend(nlargest(fallback_limit, fallback, key=hot_candidate_score))
    return CandidatePoolResult(matched, RETRIEVAL_SOURCE_SPARSE_PLUS_HOT_FALLBACK)
