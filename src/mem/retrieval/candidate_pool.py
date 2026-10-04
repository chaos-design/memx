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
    return _sparse_candidate_pool(
        all_candidates,
        matched_ids,
        frozenset(query_tokens),
        inverted_index,
        config,
        k,
    )


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


def _matched_token_count(
    mem_id: str,
    query_tokens: frozenset,
    inverted_index: Mapping[str, Set[str]],
) -> int:
    """Count how many distinct query tokens a record matches.

    输入:
        mem_id: 记忆 ID。
        query_tokens: 查询 token 集合。
        inverted_index: token 到 mem_id 集合的映射。
    输出:
        int: 命中的查询 token 数。
    示例:
        示例输入: _matched_token_count("m1", frozenset({"a", "b"}), {"a": {"m1"}})
        示例输出: 1
    """
    return sum(1 for token in query_tokens if mem_id in inverted_index.get(token, ()))


def _sparse_candidate_pool(
    all_candidates: List[EpisodicMemory],
    matched_ids: Set[str],
    query_tokens: frozenset,
    inverted_index: Mapping[str, Set[str]],
    config: MemoryConfig,
    k: int,
) -> CandidatePoolResult:
    """Build a sparse-first candidate pool with hot fallback.

    稀疏命中已足够多时，截断必须以查询相关性为主键：这些候选都已命中查询，
    差别只在命中了多少 token。若按热度截断，一条完整匹配查询的冷记忆会被
    只命中单个 token 的热记忆挤掉，而它之后再无打分机会。

    输入:
        all_candidates: 所有可检索候选。
        matched_ids: sparse 命中的 mem_id。
        query_tokens: 查询 token 集合。
        inverted_index: token 到 mem_id 集合的映射。
        config: 系统配置。
        k: 请求返回数量。
    输出:
        CandidatePoolResult: 候选池及来源。
    示例:
        示例输入: _sparse_candidate_pool([memory], {"m1"}, tokens, index, cfg, 8)
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
            nlargest(
                candidate_limit,
                matched,
                key=lambda memory: (
                    _matched_token_count(
                        memory.mem_id, query_tokens, inverted_index
                    ),
                    hot_candidate_score(memory),
                ),
            ),
            RETRIEVAL_SOURCE_SPARSE_ONLY_BOUNDED,
        )
    matched_set = {memory.mem_id for memory in matched}
    fallback = [memory for memory in all_candidates if memory.mem_id not in matched_set]
    fallback_limit = max(0, candidate_limit - len(matched))
    if fallback_limit:
        matched.extend(nlargest(fallback_limit, fallback, key=hot_candidate_score))
    return CandidatePoolResult(matched, RETRIEVAL_SOURCE_SPARSE_PLUS_HOT_FALLBACK)
