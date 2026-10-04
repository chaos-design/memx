"""Global retrieval diagnostics and FTS5-backed semantic search."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from ..config.settings import MemoryConfig
from ..embedding.scoring import f2_score
from ..embedding.vector import cosine_similarity, embed_text, tokenize
from ..memory.models import EpisodicMemory, MemoryStatus, MemoryType
from .candidate_pool import build_candidate_pool
from .diagnostics import retrieval_stats
from .pipeline import (
    DeterministicCrossEncoderReranker,
    HybridSearchPipeline,
    LocalGraphRetriever,
    LocalKeywordRetriever,
    LocalVectorRetriever,
)
from .ranking import (
    ScoredCandidate,
    dense_rank,
    filter_scored_candidates,
    hot_candidate_score,
    keyword_overlap_tokens,
    rerank_final,
    rrf_merge,
    sparse_rank,
)

FTS5_ENGINE = "sqlite_fts5"
KEYWORD_FALLBACK_ENGINE = "keyword_fallback"


def records_from_snapshot_state(
    state: Mapping[str, Any],
    config: MemoryConfig,
) -> List[EpisodicMemory]:
    """Build L2 records from a persisted scope snapshot.

    输入:
        state: `memory-state.json` 解析后的 scope snapshot。
        config: 当前 MemoryConfig。
    输出:
        list[EpisodicMemory]: 恢复出的 L2 记录。
    示例:
        示例输入: records_from_snapshot_state({"scope_id": "s", "l2": []}, config)
        示例输出: []
    """
    scope_id = str(state.get("scope_id", "default"))
    records = []
    for item in state.get("l2", []):
        if isinstance(item, Mapping):
            records.append(record_from_snapshot(item, config, scope_id))
    return records


def record_from_snapshot(
    item: Mapping[str, Any],
    config: MemoryConfig,
    default_scope_id: str,
) -> EpisodicMemory:
    """Build an L2 record from persisted JSON fields.

    输入:
        item: `EpisodicMemory.to_dict()` 风格的 JSON 字段。
        config: 当前 MemoryConfig。
        default_scope_id: 缺省 scope_id。
    输出:
        EpisodicMemory: 可用于检索评分的记录。
    示例:
        示例输入: record_from_snapshot({"mem_id": "m", "text": "x"}, config, "s")
        示例输出: EpisodicMemory(mem_id="m", ...)
    """
    text = str(item.get("text", ""))
    return EpisodicMemory(
        mem_id=str(item.get("mem_id", "")),
        embedding=embed_text(text, config.embedding_dimensions),
        text=text,
        importance=int(item.get("importance", 5)),
        ts_create=float(item.get("ts_create", 0.0)),
        ts_last_access=float(item.get("ts_last_access", item.get("ts_create", 0.0))),
        scope_id=str(item.get("scope_id", default_scope_id)),
        access_count=int(item.get("access_count", 0)),
        stability=float(item.get("stability", config.initial_stability_seconds)),
        status=MemoryStatus(str(item.get("status", MemoryStatus.ACTIVE.value))),
        source_ids=list(item.get("source_ids", [])),
        mem_type=MemoryType(str(item.get("mem_type", MemoryType.EPISODIC.value))),
    )


def fts5_global_semantic_search(
    records: Sequence[EpisodicMemory],
    query: str,
    config: MemoryConfig,
    k: int = 8,
    include_archived: bool = False,
    now_ts: Optional[float] = None,
    graph: Optional[Any] = None,
    graph_nodes: Optional[Sequence[Any]] = None,
    graph_edges: Optional[Sequence[Any]] = None,
    enable_cross_encoder: bool = True,
) -> Dict[str, Any]:
    """Run hybrid global search with vector, keyword, and graph routes.

    输入:
        records: 可检索 L2 记录集合，可跨 scope。
        query: 检索语句。
        config: 当前 MemoryConfig。
        k: 返回数量。
        include_archived: 是否包含 archived 记录。
        now_ts: 当前时间戳；None 使用 time.time()。
        graph: 可选 CognitiveGraph-compatible 对象。
        graph_nodes: 可选序列化图谱节点。
        graph_edges: 可选序列化图谱边。
        enable_cross_encoder: 是否启用可插拔重排序。
    输出:
        dict: hybrid_rrf engine、results、related 与候选统计。
    示例:
        示例输入: fts5_global_semantic_search([memory], "language", config, k=3)
        示例输出: {"engine": "hybrid_rrf", "results": [...], "related": [...]}
    """
    pipeline = HybridSearchPipeline(
        config=config,
        retrievers=[
            LocalVectorRetriever(),
            LocalKeywordRetriever(_fts5_matches),
            LocalGraphRetriever(graph=graph, nodes=graph_nodes, edges=graph_edges),
        ],
        reranker=DeterministicCrossEncoderReranker(),
    )
    return pipeline.search(
        records=records,
        query=query,
        k=k,
        include_archived=include_archived,
        now_ts=now_ts,
        enable_cross_encoder=enable_cross_encoder,
    )


def keyword_rank_records(
    records: Sequence[EpisodicMemory],
    query: str,
    k: int = 8,
    include_archived: bool = False,
) -> Dict[str, Any]:
    """Rank records by sparse keyword overlap and operational heat.

    输入:
        records: L2 记录集合。
        query: 检索语句。
        k: 返回数量。
        include_archived: 是否包含 archived 记录。
    输出:
        dict: query_tokens 和 keyword 排序结果。
    示例:
        示例输入: keyword_rank_records([memory], "memory", k=1)
        示例输出: {"results": [{"keyword_overlap": 1, ...}]}
    """
    query_tokens = frozenset(tokenize(query))
    ranked = []
    for memory in _eligible_records(records, include_archived):
        overlap = keyword_overlap_tokens(query_tokens, frozenset(tokenize(memory.text)))
        if overlap <= 0 and query_tokens:
            continue
        ranked.append(
            {
                "mem_id": memory.mem_id,
                "scope_id": memory.scope_id,
                "text": memory.text,
                "status": memory.status.value,
                "importance": memory.importance,
                "keyword_overlap": overlap,
                "hot_score": hot_candidate_score(memory),
            }
        )
    ranked = sorted(
        ranked,
        key=lambda item: (item["keyword_overlap"], item["hot_score"]),
        reverse=True,
    )[:k]
    return {
        "query": query,
        "query_tokens": sorted(query_tokens),
        "result_count": len(ranked),
        "results": ranked,
    }


def relevance_diagnostics(
    records: Sequence[EpisodicMemory],
    query: str,
    config: MemoryConfig,
    k: int = 8,
    include_archived: bool = False,
    mem_id: Optional[str] = None,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """Evaluate semantic relevance and threshold decisions.

    输入:
        records: L2 记录集合。
        query: 检索语句。
        config: 当前 MemoryConfig。
        k: 返回数量。
        include_archived: 是否包含 archived 记录。
        mem_id: 可选指定记录 ID。
        now_ts: 当前时间戳；None 使用 time.time()。
    输出:
        dict: 每条记录的 dense、keyword、F2 和 threshold 结果。
    示例:
        示例输入: relevance_diagnostics([memory], "memory", config, k=1)
        示例输出: {"results": [{"passes_relevance": True, ...}]}
    """
    if now_ts is None:
        now_ts = time.time()
    query_tokens = frozenset(tokenize(query))
    query_embedding = embed_text(query, config.embedding_dimensions)
    candidates = _eligible_records(records, include_archived)
    if mem_id is not None:
        candidates = [memory for memory in candidates if memory.mem_id == mem_id]
    scored = [
        {
            "mem_id": memory.mem_id,
            "scope_id": memory.scope_id,
            "text": memory.text,
            "status": memory.status.value,
            "scores": score_breakdown(
                memory,
                query_embedding,
                query_tokens,
                now_ts,
                config,
            ),
        }
        for memory in candidates
    ]
    scored = sorted(
        scored,
        key=lambda item: float(item["scores"]["f2_score"]),
        reverse=True,
    )[:k]
    return {
        "query": query,
        "query_tokens": sorted(query_tokens),
        "minimum_relevance_score": config.minimum_relevance_score,
        "result_count": len(scored),
        "results": scored,
    }


def hybrid_rerank_diagnostics(
    records: Sequence[EpisodicMemory],
    query: str,
    config: MemoryConfig,
    k: int = 8,
    include_archived: bool = False,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """Inspect candidate pool, dense/sparse rankings, RRF, and final rerank.

    输入:
        records: L2 记录集合。
        query: 检索语句。
        config: 当前 MemoryConfig。
        k: 返回数量。
        include_archived: 是否包含 archived 记录。
        now_ts: 当前时间戳；None 使用 time.time()。
    输出:
        dict: candidate_source、dense_ranked、sparse_ranked、fused 与 final。
    示例:
        示例输入: hybrid_rerank_diagnostics([memory], "memory", config, k=3)
        示例输出: {"candidate_source": "...", "final": [...]}
    """
    if now_ts is None:
        now_ts = time.time()
    records_by_id = {
        memory.mem_id: memory for memory in _eligible_records(records, include_archived)
    }
    token_index = {
        mem_id: frozenset(tokenize(memory.text))
        for mem_id, memory in records_by_id.items()
    }
    inverted_index = _inverted_index(token_index)
    query_tokens = frozenset(tokenize(query))
    query_embedding = embed_text(query, config.embedding_dimensions)
    pool = build_candidate_pool(
        records=records_by_id,
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
    candidate_limit = min(
        len(scored_candidates),
        max(k, k * config.retrieval_candidate_multiplier),
    )
    dense_ranked = dense_rank(scored_candidates, candidate_limit)
    sparse_ranked = sparse_rank(scored_candidates, candidate_limit)
    fused = rrf_merge([dense_ranked, sparse_ranked], config.rrf_k0)
    final = rerank_final(fused, query_embedding, now_ts, config, k) if fused else []
    stats = retrieval_stats(
        scope_id="global" if _is_multi_scope(records_by_id.values()) else _scope_id(
            records_by_id.values()
        ),
        query_tokens=query_tokens,
        candidate_count=len(pool.candidates),
        filtered_count=len(scored_candidates),
        dense_ranked=len(dense_ranked),
        sparse_ranked=len(sparse_ranked),
        candidate_source=pool.source,
        candidate_limit=config.retrieval_candidate_hard_limit,
    )
    return {
        "query": query,
        "query_tokens": sorted(query_tokens),
        "candidate_source": pool.source,
        "stats": stats,
        "scored_candidates": _scored_payload(scored_candidates, query_tokens),
        "dense_ranked": _memory_list_payload(dense_ranked),
        "sparse_ranked": _memory_list_payload(sparse_ranked),
        "fused": _memory_list_payload(fused),
        "final": _memory_list_payload(final),
    }


def score_breakdown(
    memory: EpisodicMemory,
    query_embedding: Sequence[float],
    query_tokens: frozenset,
    now_ts: float,
    config: MemoryConfig,
) -> Dict[str, Any]:
    """Compute dense, keyword, recency, importance, and F2 score components.

    输入:
        memory: L2 记录。
        query_embedding: query embedding。
        query_tokens: query token 集合。
        now_ts: 当前时间戳。
        config: 当前 MemoryConfig。
    输出:
        dict: 分数明细和 relevance threshold 结果。
    示例:
        示例输入: score_breakdown(memory, embedding, frozenset({"a"}), 1.0, config)
        示例输出: {"dense_similarity": 0.1, "f2_score": 0.2, ...}
    """
    dense = cosine_similarity(query_embedding, memory.embedding)
    overlap = keyword_overlap_tokens(query_tokens, frozenset(tokenize(memory.text)))
    elapsed_hours = max(0.0, now_ts - memory.ts_last_access) / 3_600.0
    recency = config.recency_decay_per_hour**elapsed_hours
    importance = memory.importance / 10.0
    keyword_score = overlap / max(1, len(query_tokens))
    return {
        "dense_similarity": dense,
        "keyword_overlap": overlap,
        "keyword_score": keyword_score,
        "recency_score": recency,
        "importance_score": importance,
        "f2_score": f2_score(memory, query_embedding, now_ts, config),
        "passes_relevance": dense >= config.minimum_relevance_score or overlap > 0,
        "weights": {
            "relevance": config.f2_weight_relevance,
            "recency": config.f2_weight_recency,
            "importance": config.f2_weight_importance,
        },
    }


def _eligible_records(
    records: Sequence[EpisodicMemory],
    include_archived: bool,
) -> List[EpisodicMemory]:
    """Filter records eligible for retrieval.

    输入:
        records: L2 记录集合。
        include_archived: 是否包含 archived。
    输出:
        list[EpisodicMemory]: 可检索记录。
    示例:
        示例输入: _eligible_records([memory], False)
        示例输出: active 记录列表。
    """
    statuses = {MemoryStatus.ACTIVE}
    if include_archived:
        statuses.add(MemoryStatus.ARCHIVED)
    return [memory for memory in records if memory.status in statuses]


def _fts5_matches(
    records: Sequence[EpisodicMemory],
    query_tokens: frozenset,
    limit: int,
) -> Dict[str, Any]:
    """Return FTS5 matches with a keyword fallback.

    输入:
        records: 可检索 L2 记录集合。
        query_tokens: query token 集合。
        limit: 最大返回数量。
    输出:
        dict: engine 和 matches。
    示例:
        示例输入: _fts5_matches([memory], frozenset({"memory"}), 8)
        示例输出: {"engine": "sqlite_fts5", "matches": [...]}
    """
    if not query_tokens or not records:
        return {"engine": FTS5_ENGINE, "matches": []}
    query = _fts5_query(query_tokens)
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute(
            (
                "CREATE VIRTUAL TABLE memory_fts USING fts5("
                "mem_id UNINDEXED, scope_id UNINDEXED, text, "
                "status UNINDEXED, importance UNINDEXED)"
            )
        )
        connection.executemany(
            "INSERT INTO memory_fts(mem_id, scope_id, text, status, importance) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    memory.mem_id,
                    memory.scope_id,
                    memory.text,
                    memory.status.value,
                    memory.importance,
                )
                for memory in records
            ],
        )
        rows = connection.execute(
            (
                "SELECT mem_id, scope_id, text, bm25(memory_fts) AS rank "
                "FROM memory_fts WHERE memory_fts MATCH ? ORDER BY rank LIMIT ?"
            ),
            (query, limit),
        ).fetchall()
    except sqlite3.Error:
        return _keyword_fallback_matches(records, query_tokens, limit)
    finally:
        try:
            connection.close()
        except UnboundLocalError:
            pass
    matches = []
    for index, row in enumerate(rows):
        matches.append(
            {
                "mem_id": str(row[0]),
                "scope_id": str(row[1]),
                "text": str(row[2]),
                "fts_rank": float(row[3]),
                "fts_score": 1 / (index + 1),
            }
        )
    return {"engine": FTS5_ENGINE, "matches": matches}


def _keyword_fallback_matches(
    records: Sequence[EpisodicMemory],
    query_tokens: frozenset,
    limit: int,
) -> Dict[str, Any]:
    """Return sparse keyword matches when FTS5 is unavailable.

    输入:
        records: 可检索 L2 记录集合。
        query_tokens: query token 集合。
        limit: 最大返回数量。
    输出:
        dict: keyword fallback matches。
    示例:
        示例输入: _keyword_fallback_matches([memory], frozenset({"a"}), 8)
        示例输出: {"engine": "keyword_fallback", "matches": [...]}
    """
    matches = []
    for memory in records:
        overlap = keyword_overlap_tokens(query_tokens, frozenset(tokenize(memory.text)))
        if overlap <= 0:
            continue
        matches.append(
            {
                "mem_id": memory.mem_id,
                "scope_id": memory.scope_id,
                "text": memory.text,
                "fts_rank": -float(overlap),
                "fts_score": float(overlap),
            }
        )
    matches = sorted(matches, key=lambda item: item["fts_score"], reverse=True)[:limit]
    return {"engine": KEYWORD_FALLBACK_ENGINE, "matches": matches}


def _fts5_query(query_tokens: Iterable[str]) -> str:
    """Build a safe OR query for FTS5 token matching.

    输入:
        query_tokens: query token 集合。
    输出:
        str: FTS5 MATCH 查询字符串。
    示例:
        示例输入: _fts5_query(["agent", "memory"])
        示例输出: "\"agent\" OR \"memory\""
    """
    quoted = []
    for token in query_tokens:
        escaped = token.replace('"', '""')
        quoted.append(f'"{escaped}"')
    return " OR ".join(quoted)


def _global_candidate_set(
    records: Sequence[EpisodicMemory],
    query_embedding: Sequence[float],
    query_tokens: frozenset,
    fts_scores: Mapping[str, float],
    config: MemoryConfig,
    k: int,
) -> List[EpisodicMemory]:
    """Build a bounded candidate set from FTS, semantic, and hot signals.

    输入:
        records: 可检索 L2 记录集合。
        query_embedding: query embedding。
        query_tokens: query token 集合。
        fts_scores: mem_id 到 FTS 分数的映射。
        config: 当前 MemoryConfig。
        k: 目标返回数量。
    输出:
        list[EpisodicMemory]: 候选集合。
    示例:
        示例输入: _global_candidate_set([memory], embedding, tokens, {}, config, 8)
        示例输出: [memory]
    """
    limit = min(
        len(records),
        max(k, k * config.retrieval_candidate_multiplier * 4),
    )
    by_id = {memory.mem_id: memory for memory in records}
    selected: Dict[str, EpisodicMemory] = {
        mem_id: by_id[mem_id] for mem_id in fts_scores if mem_id in by_id
    }
    semantic = sorted(
        records,
        key=lambda memory: cosine_similarity(query_embedding, memory.embedding),
        reverse=True,
    )[:limit]
    keyword = sorted(
        records,
        key=lambda memory: keyword_overlap_tokens(
            query_tokens,
            frozenset(tokenize(memory.text)),
        ),
        reverse=True,
    )[:limit]
    hot = sorted(records, key=hot_candidate_score, reverse=True)[: max(k, 1)]
    for memory in semantic + keyword + hot:
        selected.setdefault(memory.mem_id, memory)
        if len(selected) >= limit:
            break
    return list(selected.values())


def _inverted_index(token_index: Mapping[str, frozenset]) -> Dict[str, Set[str]]:
    """Build a token inverted index for diagnostics.

    输入:
        token_index: mem_id 到 token 集合映射。
    输出:
        dict[str, set[str]]: token 到 mem_id 的倒排索引。
    示例:
        示例输入: _inverted_index({"m1": frozenset({"a"})})
        示例输出: {"a": {"m1"}}
    """
    index: Dict[str, Set[str]] = {}
    for mem_id, tokens in token_index.items():
        for token in tokens:
            index.setdefault(token, set()).add(mem_id)
    return index


def _scored_payload(
    scored_candidates: List[ScoredCandidate],
    query_tokens: frozenset,
) -> List[Dict[str, Any]]:
    """Serialize scored candidates.

    输入:
        scored_candidates: dense/sparse 评分候选。
        query_tokens: query token 集合。
    输出:
        list[dict]: 可 JSON 序列化的候选列表。
    示例:
        示例输入: _scored_payload([(memory, 0.5, 1)], frozenset({"a"}))
        示例输出: [{"mem_id": "...", "dense_similarity": 0.5, ...}]
    """
    return [
        {
            "mem_id": memory.mem_id,
            "scope_id": memory.scope_id,
            "text": memory.text,
            "dense_similarity": dense,
            "keyword_overlap": overlap,
            "keyword_score": overlap / max(1, len(query_tokens)),
        }
        for memory, dense, overlap in scored_candidates
    ]


def _memory_list_payload(records: Sequence[EpisodicMemory]) -> List[Dict[str, Any]]:
    """Serialize memory ranking lists.

    输入:
        records: L2 记录列表。
    输出:
        list[dict]: 排名结果摘要。
    示例:
        示例输入: _memory_list_payload([memory])
        示例输出: [{"mem_id": "...", "text": "..."}]
    """
    return [
        {
            "mem_id": memory.mem_id,
            "scope_id": memory.scope_id,
            "text": memory.text,
            "status": memory.status.value,
            "importance": memory.importance,
        }
        for memory in records
    ]


def _is_multi_scope(records: Iterable[EpisodicMemory]) -> bool:
    """Return whether records span multiple scopes.

    输入:
        records: L2 记录集合。
    输出:
        bool: 多 scope 时为 True。
    示例:
        示例输入: _is_multi_scope([memory])
        示例输出: False
    """
    return len({memory.scope_id for memory in records}) > 1


def _scope_id(records: Iterable[EpisodicMemory]) -> str:
    """Return the only scope id in records or global.

    输入:
        records: L2 记录集合。
    输出:
        str: 单一 scope_id 或 global。
    示例:
        示例输入: _scope_id([memory])
        示例输出: "scope"
    """
    scopes = {memory.scope_id for memory in records}
    if len(scopes) == 1:
        return next(iter(scopes))
    return "global"
