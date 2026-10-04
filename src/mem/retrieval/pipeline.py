"""Pluggable hybrid retrieval pipeline with vector, keyword, and graph routes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Set

from ..config.settings import MemoryConfig
from ..embedding.vector import cosine_similarity, embed_text, tokenize
from ..memory.models import EpisodicMemory, MemoryStatus
from ..models.enums import InsightStatus
from .ranking import keyword_overlap_tokens

HYBRID_RRF_ENGINE = "hybrid_rrf"
VECTOR_ROUTE = "vector"
KEYWORD_ROUTE = "keyword"
GRAPH_ROUTE = "graph"
RELATED_ROUTE = "graph_related"

KeywordMatchFn = Callable[
    [Sequence[EpisodicMemory], frozenset, int],
    Mapping[str, Any],
]


@dataclass(frozen=True)
class SearchRequest:
    """Normalized search request shared by retrieval routes."""

    query: str
    query_tokens: frozenset
    query_embedding: Sequence[float]
    k: int
    include_archived: bool
    now_ts: float
    config: MemoryConfig


@dataclass(frozen=True)
class RetrievalCandidate:
    """Candidate produced by one retrieval route."""

    mem_id: str
    rank: int
    score: float
    route: str
    engine: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteResult:
    """Ranked candidates produced by a retrieval route."""

    route: str
    engine: str
    candidates: List[RetrievalCandidate]


@dataclass
class FusedCandidate:
    """Candidate after RRF fusion and final scoring."""

    memory: EpisodicMemory
    rrf_score: float
    route_hits: List[str]
    route_scores: Dict[str, float]
    route_ranks: Dict[str, int]
    scores: Dict[str, Any]
    combined_score: float
    rerank_score: float = 0.0


class Retriever(Protocol):
    """Port implemented by vector, keyword, and graph retrievers."""

    route: str

    def retrieve(
        self,
        records: Sequence[EpisodicMemory],
        request: SearchRequest,
    ) -> RouteResult:
        """Return ranked retrieval candidates.

        输入:
            records: 当前检索范围内可检索的 L2 记录。
            request: 标准化检索请求。
        输出:
            RouteResult: 当前路由的排序候选。
        示例:
            示例输入: retriever.retrieve([memory], request)
            示例输出: RouteResult(route="vector", candidates=[...])
        """


class CrossEncoderReranker(Protocol):
    """Optional reranker Port used after RRF and three-dimensional scoring."""

    def rerank(
        self,
        candidates: List[FusedCandidate],
        request: SearchRequest,
        k: int,
    ) -> List[FusedCandidate]:
        """Return reranked fused candidates.

        输入:
            candidates: RRF 与综合评分后的候选。
            request: 标准化检索请求。
            k: 返回数量上限。
        输出:
            list[FusedCandidate]: 重排后的候选。
        示例:
            示例输入: reranker.rerank([candidate], request, 8)
            示例输出: [candidate]
        """


class LocalVectorRetriever:
    """Local vector retriever backed by deterministic embeddings."""

    route = VECTOR_ROUTE
    engine = "local_vector"

    def retrieve(
        self,
        records: Sequence[EpisodicMemory],
        request: SearchRequest,
    ) -> RouteResult:
        """Rank records by dense cosine similarity.

        输入:
            records: 可检索 L2 记录。
            request: 标准化检索请求。
        输出:
            RouteResult: dense 路由候选。
        示例:
            示例输入: LocalVectorRetriever().retrieve([memory], request)
            示例输出: RouteResult(route="vector", candidates=[...])
        """
        limit = _route_limit(len(records), request.k, request.config)
        scored = []
        for memory in records:
            score = cosine_similarity(request.query_embedding, memory.embedding)
            if score >= request.config.minimum_relevance_score:
                scored.append((memory, score))
        ranked = sorted(scored, key=lambda item: item[1], reverse=True)[:limit]
        candidates = [
            RetrievalCandidate(
                mem_id=memory.mem_id,
                rank=index + 1,
                score=score,
                route=self.route,
                engine=self.engine,
                metadata={"dense_similarity": score},
            )
            for index, (memory, score) in enumerate(ranked)
        ]
        return RouteResult(self.route, self.engine, candidates)


class LocalKeywordRetriever:
    """Local keyword retriever backed by SQLite FTS5 or fallback matching."""

    route = KEYWORD_ROUTE

    def __init__(self, match_fn: KeywordMatchFn) -> None:
        """Initialize the keyword retriever.

        输入:
            match_fn: FTS5/fallback 匹配函数。
        输出:
            None。
        示例:
            示例输入: LocalKeywordRetriever(_fts5_matches)
            示例输出: keyword retriever 实例。
        """
        self.match_fn = match_fn

    def retrieve(
        self,
        records: Sequence[EpisodicMemory],
        request: SearchRequest,
    ) -> RouteResult:
        """Rank records by keyword route results.

        输入:
            records: 可检索 L2 记录。
            request: 标准化检索请求。
        输出:
            RouteResult: keyword 路由候选。
        示例:
            示例输入: retriever.retrieve([memory], request)
            示例输出: RouteResult(route="keyword", candidates=[...])
        """
        if not request.query_tokens:
            return RouteResult(self.route, "keyword_empty", [])
        limit = _route_limit(len(records), request.k, request.config)
        result = self.match_fn(records, request.query_tokens, limit)
        engine = str(result.get("engine", "keyword"))
        candidates = [
            RetrievalCandidate(
                mem_id=str(item["mem_id"]),
                rank=index + 1,
                score=float(item.get("fts_score", 0.0)),
                route=self.route,
                engine=engine,
                metadata={
                    "fts_rank": float(item.get("fts_rank", 0.0)),
                    "keyword_engine": engine,
                },
            )
            for index, item in enumerate(result.get("matches", []))
        ]
        return RouteResult(self.route, engine, candidates)


class LocalGraphRetriever:
    """Local graph retriever backed by CognitiveGraph or serialized graph data."""

    route = GRAPH_ROUTE
    engine = "local_graph"

    def __init__(
        self,
        graph: Optional[Any] = None,
        nodes: Optional[Sequence[Any]] = None,
        edges: Optional[Sequence[Any]] = None,
    ) -> None:
        """Initialize graph-backed retrieval.

        输入:
            graph: 可选 CognitiveGraph-compatible 对象。
            nodes: 可选序列化节点集合。
            edges: 可选序列化边集合。
        输出:
            None。
        示例:
            示例输入: LocalGraphRetriever(graph)
            示例输出: graph retriever 实例。
        """
        self.graph = graph
        self.nodes = list(nodes or [])
        self.edges = list(edges or [])

    def retrieve(
        self,
        records: Sequence[EpisodicMemory],
        request: SearchRequest,
    ) -> RouteResult:
        """Rank memories discovered through graph labels and neighbors.

        输入:
            records: 可检索 L2 记录。
            request: 标准化检索请求。
        输出:
            RouteResult: graph 路由候选。
        示例:
            示例输入: retriever.retrieve([memory], request)
            示例输出: RouteResult(route="graph", candidates=[...])
        """
        if not request.query_tokens:
            return RouteResult(self.route, self.engine, [])
        scores = self._graph_scores(records, request.query_tokens)
        limit = _route_limit(len(records), request.k, request.config)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
        candidates = [
            RetrievalCandidate(
                mem_id=mem_id,
                rank=index + 1,
                score=score,
                route=self.route,
                engine=self.engine,
                metadata={"graph_score": score},
            )
            for index, (mem_id, score) in enumerate(ranked)
        ]
        return RouteResult(self.route, self.engine, candidates)

    def related(
        self,
        records: Sequence[EpisodicMemory],
        main_mem_ids: Set[str],
        limit: int,
    ) -> List[RetrievalCandidate]:
        """Return graph-expanded related memories for main results.

        输入:
            records: 可检索 L2 记录。
            main_mem_ids: Top-K 主结果 mem_id 集合。
            limit: related 数量上限。
        输出:
            list[RetrievalCandidate]: 去重后的关联记忆候选。
        示例:
            示例输入: retriever.related([memory], {"m1"}, 8)
            示例输出: [RetrievalCandidate(mem_id="m2", ...)]
        """
        if not main_mem_ids or limit <= 0:
            return []
        eligible_ids = {memory.mem_id for memory in records}
        related_scores: Dict[str, float] = {}
        for scope_id in _record_scopes(records):
            nodes = self._nodes_for_scope(scope_id)
            edges = self._edges_for_scope(scope_id)
            node_by_id = {_node_id(node): node for node in nodes}
            seed_ids = {
                node_id
                for node_id, node in node_by_id.items()
                if main_mem_ids.intersection(_node_evidence_ids(node))
            }
            for node_id in seed_ids:
                node = node_by_id[node_id]
                self._add_evidence_scores(
                    related_scores,
                    _node_evidence_ids(node),
                    _node_salience(node),
                    eligible_ids,
                    main_mem_ids,
                )
            for edge in edges:
                source_id = _edge_source_id(edge)
                target_id = _edge_target_id(edge)
                if source_id in seed_ids:
                    self._score_neighbor(
                        target_id,
                        edge,
                        node_by_id,
                        related_scores,
                        eligible_ids,
                        main_mem_ids,
                    )
                if target_id in seed_ids:
                    self._score_neighbor(
                        source_id,
                        edge,
                        node_by_id,
                        related_scores,
                        eligible_ids,
                        main_mem_ids,
                    )
        ranked = sorted(
            related_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:limit]
        return [
            RetrievalCandidate(
                mem_id=mem_id,
                rank=index + 1,
                score=score,
                route=RELATED_ROUTE,
                engine=self.engine,
                metadata={"related_score": score},
            )
            for index, (mem_id, score) in enumerate(ranked)
        ]

    def _graph_scores(
        self,
        records: Sequence[EpisodicMemory],
        query_tokens: frozenset,
    ) -> Dict[str, float]:
        """Return graph route scores keyed by memory ID.

        输入:
            records: 可检索 L2 记录。
            query_tokens: 查询 token 集合。
        输出:
            dict[str, float]: mem_id 到图谱分。
        示例:
            示例输入: self._graph_scores([memory], frozenset({"agent"}))
            示例输出: {"m1": 0.9}
        """
        eligible_ids = {memory.mem_id for memory in records}
        scores: Dict[str, float] = {}
        for scope_id in _record_scopes(records):
            nodes = self._nodes_for_scope(scope_id)
            edges = self._edges_for_scope(scope_id)
            node_by_id = {_node_id(node): node for node in nodes}
            matched = self._matched_node_scores(nodes, query_tokens)
            for node_id, node_score in matched.items():
                node = node_by_id[node_id]
                self._add_evidence_scores(
                    scores,
                    _node_evidence_ids(node),
                    node_score,
                    eligible_ids,
                    set(),
                )
            for edge in edges:
                source_id = _edge_source_id(edge)
                target_id = _edge_target_id(edge)
                if source_id in matched:
                    self._score_neighbor(
                        target_id,
                        edge,
                        node_by_id,
                        scores,
                        eligible_ids,
                        set(),
                        matched[source_id],
                    )
                if target_id in matched:
                    self._score_neighbor(
                        source_id,
                        edge,
                        node_by_id,
                        scores,
                        eligible_ids,
                        set(),
                        matched[target_id],
                    )
        return scores

    def _matched_node_scores(
        self,
        nodes: Sequence[Any],
        query_tokens: frozenset,
    ) -> Dict[str, float]:
        """Score graph nodes whose labels match query tokens.

        输入:
            nodes: 图谱节点集合。
            query_tokens: 查询 token 集合。
        输出:
            dict[str, float]: node_id 到匹配分。
        示例:
            示例输入: self._matched_node_scores([node], frozenset({"agent"}))
            示例输出: {"node-id": 1.2}
        """
        matched: Dict[str, float] = {}
        for node in nodes:
            label = _node_label(node)
            label_tokens = frozenset(tokenize(label))
            overlap = keyword_overlap_tokens(query_tokens, label_tokens)
            substring = any(token in label.lower() for token in query_tokens)
            if overlap <= 0 and not substring:
                continue
            matched[_node_id(node)] = _node_salience(node) + float(max(overlap, 1))
        return matched

    def _score_neighbor(
        self,
        node_id: str,
        edge: Any,
        node_by_id: Mapping[str, Any],
        scores: Dict[str, float],
        eligible_ids: Set[str],
        excluded_ids: Set[str],
        base_score: float = 1.0,
    ) -> None:
        """Add attenuated neighbor evidence scores.

        输入:
            node_id: 邻居节点 ID。
            edge: 连接边。
            node_by_id: node_id 到节点的映射。
            scores: 待更新的 mem_id 分数字典。
            eligible_ids: 可返回的 mem_id。
            excluded_ids: 需要排除的主结果 mem_id。
            base_score: 种子节点分。
        输出:
            None。
        示例:
            示例输入: self._score_neighbor("n2", edge, nodes, scores, ids, set())
            示例输出: scores 可能新增邻居 evidence 分数。
        """
        node = node_by_id.get(node_id)
        if node is None:
            return
        score = 0.8 * base_score * max(_edge_weight(edge), 0.01)
        self._add_evidence_scores(
            scores,
            _node_evidence_ids(node),
            score,
            eligible_ids,
            excluded_ids,
        )

    def _add_evidence_scores(
        self,
        scores: Dict[str, float],
        evidence_ids: Sequence[str],
        score: float,
        eligible_ids: Set[str],
        excluded_ids: Set[str],
    ) -> None:
        """Add evidence scores for eligible memories.

        输入:
            scores: 待更新的 mem_id 分数字典。
            evidence_ids: 图节点关联的证据 ID。
            score: 本次累积分。
            eligible_ids: 可返回的 mem_id。
            excluded_ids: 需要排除的 mem_id。
        输出:
            None。
        示例:
            示例输入: self._add_evidence_scores(scores, ["m1"], 0.5, {"m1"}, set())
            示例输出: scores["m1"] 增加 0.5。
        """
        for mem_id in evidence_ids:
            if mem_id not in eligible_ids or mem_id in excluded_ids:
                continue
            scores[mem_id] = scores.get(mem_id, 0.0) + score

    def _nodes_for_scope(self, scope_id: str) -> List[Any]:
        """Return graph nodes for one scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[Any]: 图节点列表。
        示例:
            示例输入: self._nodes_for_scope("scope")
            示例输出: [GraphNode(...)]
        """
        if self.graph is not None:
            # 与 graph_query / subgraph_for_context 同口径：SUPERSEDED 洞察依赖
            # 已被替换的 L3 证据，若在此放行，级联失效会在 RRF 融合阶段被抵消。
            # 过滤发生在消费侧而非 all_nodes 内部，audit 与快照仍需看到全量。
            return [
                node
                for node in self.graph.all_nodes(scope_id)
                if getattr(node, "status", None) is not InsightStatus.SUPERSEDED
            ]
        return [node for node in self.nodes if _node_scope_id(node) == scope_id]

    def _edges_for_scope(self, scope_id: str) -> List[Any]:
        """Return graph edges for one scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[Any]: 图边列表。
        示例:
            示例输入: self._edges_for_scope("scope")
            示例输出: [GraphEdge(...)]
        """
        if self.graph is not None:
            return list(self.graph.all_edges(scope_id))
        return [edge for edge in self.edges if _edge_scope_id(edge) == scope_id]


class DeterministicCrossEncoderReranker:
    """Dependency-free reranker that mimics a cross-encoder boundary."""

    def rerank(
        self,
        candidates: List[FusedCandidate],
        request: SearchRequest,
        k: int,
    ) -> List[FusedCandidate]:
        """Rerank fused candidates with deterministic local signals.

        输入:
            candidates: RRF 与综合评分后的候选。
            request: 标准化检索请求。
            k: 返回数量上限。
        输出:
            list[FusedCandidate]: 重排序后的候选。
        示例:
            示例输入: DeterministicCrossEncoderReranker().rerank([candidate], req, 1)
            示例输出: [candidate]
        """
        for candidate in candidates:
            route_coverage = min(1.0, len(candidate.route_hits) / 3.0)
            candidate.rerank_score = (
                0.75 * candidate.combined_score
                + 0.15 * candidate.rrf_score
                + 0.10 * route_coverage
            )
        return sorted(
            candidates,
            key=lambda item: (
                item.rerank_score,
                item.combined_score,
                item.rrf_score,
            ),
            reverse=True,
        )[:k]


class HybridSearchPipeline:
    """Orchestrate multi-route retrieval, fusion, rerank, and related expansion."""

    def __init__(
        self,
        config: MemoryConfig,
        retrievers: Sequence[Retriever],
        reranker: Optional[CrossEncoderReranker] = None,
    ) -> None:
        """Initialize a hybrid retrieval pipeline.

        输入:
            config: MemoryConfig 配置对象。
            retrievers: 三路或多路检索 Port 实例。
            reranker: 可选重排序 Port。
        输出:
            None。
        示例:
            示例输入: HybridSearchPipeline(config, [LocalVectorRetriever()])
            示例输出: pipeline 实例。
        """
        self.config = config
        self.retrievers = list(retrievers)
        self.reranker = reranker or DeterministicCrossEncoderReranker()

    def search(
        self,
        records: Sequence[EpisodicMemory],
        query: str,
        k: int = 8,
        include_archived: bool = False,
        now_ts: Optional[float] = None,
        enable_cross_encoder: bool = True,
    ) -> Dict[str, Any]:
        """Run hybrid retrieval and return a JSON-ready payload.

        输入:
            records: 可检索 L2 记录集合。
            query: 检索语句。
            k: Top-K 主结果数量。
            include_archived: 是否包含 archived 记忆。
            now_ts: 当前时间戳；None 使用 time.time()。
            enable_cross_encoder: 是否启用 reranker Port。
        输出:
            dict: 包含 results 与 related 的检索 payload。
        示例:
            示例输入: pipeline.search([memory], "agent", k=3)
            示例输出: {"engine": "hybrid_rrf", "results": [...], "related": [...]}
        """
        now = time.time() if now_ts is None else now_ts
        query_tokens = frozenset(tokenize(query))
        query_embedding = embed_text(query, self.config.embedding_dimensions)
        eligible = _eligible_records(records, include_archived)
        request = SearchRequest(
            query=query,
            query_tokens=query_tokens,
            query_embedding=query_embedding,
            k=k,
            include_archived=include_archived,
            now_ts=now,
            config=self.config,
        )
        if k <= 0 or not query_tokens:
            return self._empty_payload(query, query_tokens, len(eligible))
        route_results, route_errors = self._run_routes(eligible, request)
        fused_candidates = self._fuse(route_results, eligible, request)
        if enable_cross_encoder and fused_candidates:
            fused, rerank_error = self._rerank(fused_candidates, request, k)
        else:
            rerank_error = None
            fused = sorted(
                fused_candidates,
                key=lambda item: (item.combined_score, item.rrf_score),
                reverse=True,
            )[:k]
        related = self._related(eligible, fused, request)
        payload = {
            "engine": HYBRID_RRF_ENGINE,
            "query": query,
            "query_tokens": sorted(query_tokens),
            "candidate_count": len(eligible),
            "fused_candidate_count": len(fused_candidates),
            "result_count": len(fused),
            "related_count": len(related),
            "routes": _routes_payload(route_results),
            "route_errors": route_errors,
            "rerank_enabled": enable_cross_encoder,
            "rerank_error": rerank_error,
            "results": [_result_payload(candidate) for candidate in fused],
            "related": [_related_payload(candidate, eligible) for candidate in related],
        }
        payload["fts_match_count"] = payload["routes"].get(
            KEYWORD_ROUTE,
            {},
        ).get("candidate_count", 0)
        payload["keyword_engine"] = payload["routes"].get(KEYWORD_ROUTE, {}).get(
            "engine",
            "keyword_unavailable",
        )
        return payload

    def _run_routes(
        self,
        records: Sequence[EpisodicMemory],
        request: SearchRequest,
    ) -> tuple[List[RouteResult], Dict[str, str]]:
        """Run every configured retriever and collect non-fatal failures.

        输入:
            records: 可检索 L2 记录。
            request: 标准化检索请求。
        输出:
            tuple: RouteResult 列表与 route_errors 字典。
        示例:
            示例输入: self._run_routes([memory], request)
            示例输出: ([RouteResult(...)], {})
        """
        results: List[RouteResult] = []
        errors: Dict[str, str] = {}
        for retriever in self.retrievers:
            try:
                results.append(retriever.retrieve(records, request))
            except Exception as exc:  # pragma: no cover - defensive adapter boundary
                errors[getattr(retriever, "route", "unknown")] = str(exc)
        return results, errors

    def _fuse(
        self,
        route_results: Sequence[RouteResult],
        records: Sequence[EpisodicMemory],
        request: SearchRequest,
    ) -> List[FusedCandidate]:
        """Fuse route rankings by memory ID and calculate final scores.

        输入:
            route_results: 三路召回结果。
            records: 可检索 L2 记录。
            request: 标准化检索请求。
        输出:
            list[FusedCandidate]: 融合并评分后的候选。
        示例:
            示例输入: self._fuse([route_result], [memory], request)
            示例输出: [FusedCandidate(memory=memory, ...)]
        """
        by_id = {memory.mem_id: memory for memory in records}
        rrf_scores: Dict[str, float] = {}
        route_hits: Dict[str, List[str]] = {}
        route_scores: Dict[str, Dict[str, float]] = {}
        route_ranks: Dict[str, Dict[str, int]] = {}
        for result in route_results:
            for candidate in result.candidates:
                if candidate.mem_id not in by_id:
                    continue
                rrf_scores[candidate.mem_id] = rrf_scores.get(candidate.mem_id, 0.0)
                rrf_scores[candidate.mem_id] += 1 / (
                    request.config.rrf_k0 + candidate.rank
                )
                route_hits.setdefault(candidate.mem_id, []).append(candidate.route)
                route_scores.setdefault(candidate.mem_id, {})[
                    candidate.route
                ] = candidate.score
                route_ranks.setdefault(candidate.mem_id, {})[
                    candidate.route
                ] = candidate.rank
        fused = []
        for mem_id, rrf_score in rrf_scores.items():
            memory = by_id[mem_id]
            scores = score_dimensions(
                memory,
                request.query_embedding,
                request.query_tokens,
                request.now_ts,
                request.config,
                route_hits.get(mem_id, []),
            )
            fused.append(
                FusedCandidate(
                    memory=memory,
                    rrf_score=rrf_score,
                    route_hits=sorted(set(route_hits.get(mem_id, []))),
                    route_scores=route_scores.get(mem_id, {}),
                    route_ranks=route_ranks.get(mem_id, {}),
                    scores=scores,
                    combined_score=float(scores["combined_score"]),
                )
            )
        return sorted(
            fused,
            key=lambda item: (item.rrf_score, item.combined_score),
            reverse=True,
        )

    def _rerank(
        self,
        candidates: List[FusedCandidate],
        request: SearchRequest,
        k: int,
    ) -> tuple[List[FusedCandidate], Optional[str]]:
        """Apply the configured reranker with deterministic fallback.

        输入:
            candidates: 融合候选。
            request: 标准化检索请求。
            k: 返回数量上限。
        输出:
            tuple: 重排候选与可选错误信息。
        示例:
            示例输入: self._rerank([candidate], request, 1)
            示例输出: ([candidate], None)
        """
        try:
            return self.reranker.rerank(candidates, request, k), None
        except Exception as exc:  # pragma: no cover - defensive adapter boundary
            fallback = sorted(
                candidates,
                key=lambda item: (item.combined_score, item.rrf_score),
                reverse=True,
            )[:k]
            return fallback, str(exc)

    def _related(
        self,
        records: Sequence[EpisodicMemory],
        main_candidates: Sequence[FusedCandidate],
        request: SearchRequest,
    ) -> List[RetrievalCandidate]:
        """Expand Top-K results through graph related memories.

        输入:
            records: 可检索 L2 记录。
            main_candidates: Top-K 主结果候选。
            request: 标准化检索请求。
        输出:
            list[RetrievalCandidate]: related 候选。
        示例:
            示例输入: self._related([memory], [candidate], request)
            示例输出: [RetrievalCandidate(...)]
        """
        main_ids = {candidate.memory.mem_id for candidate in main_candidates}
        limit = max(request.k, 1)
        for retriever in self.retrievers:
            related_fn = getattr(retriever, "related", None)
            if related_fn is not None:
                return related_fn(records, main_ids, limit)
        return []

    def _empty_payload(
        self,
        query: str,
        query_tokens: frozenset,
        candidate_count: int,
    ) -> Dict[str, Any]:
        """Return a stable empty search payload.

        输入:
            query: 检索语句。
            query_tokens: 查询 token 集合。
            candidate_count: 可检索记录数量。
        输出:
            dict: 空结果 payload。
        示例:
            示例输入: self._empty_payload("", frozenset(), 0)
            示例输出: {"results": [], "related": []}
        """
        return {
            "engine": HYBRID_RRF_ENGINE,
            "query": query,
            "query_tokens": sorted(query_tokens),
            "candidate_count": candidate_count,
            "fused_candidate_count": 0,
            "fts_match_count": 0,
            "result_count": 0,
            "related_count": 0,
            "routes": {},
            "route_errors": {},
            "rerank_enabled": False,
            "rerank_error": None,
            "keyword_engine": "keyword_empty",
            "results": [],
            "related": [],
        }


def score_dimensions(
    memory: EpisodicMemory,
    query_embedding: Sequence[float],
    query_tokens: frozenset,
    now_ts: float,
    config: MemoryConfig,
    route_hits: Sequence[str],
) -> Dict[str, Any]:
    """Compute relevance, recency, importance, and combined scores.

    输入:
        memory: L2 记忆对象。
        query_embedding: query 向量。
        query_tokens: query token 集合。
        now_ts: 当前时间戳。
        config: MemoryConfig 配置对象。
        route_hits: 命中的检索路由。
    输出:
        dict: 三维评分明细。
    示例:
        示例输入: score_dimensions(memory, embedding, frozenset({"a"}), 1.0, cfg, [])
        示例输出: {"combined_score": 0.5, ...}
    """
    dense = cosine_similarity(query_embedding, memory.embedding)
    overlap = keyword_overlap_tokens(query_tokens, frozenset(tokenize(memory.text)))
    keyword_score = overlap / max(1, len(query_tokens))
    graph_bonus = 0.1 if GRAPH_ROUTE in route_hits else 0.0
    relevance = min(1.0, 0.7 * max(0.0, dense) + 0.3 * keyword_score + graph_bonus)
    elapsed_hours = max(0.0, now_ts - memory.ts_last_access) / 3_600.0
    recency = config.recency_decay_per_hour**elapsed_hours
    importance = memory.importance / 10.0
    combined = (
        config.f2_weight_relevance * relevance
        + config.f2_weight_recency * recency
        + config.f2_weight_importance * importance
    )
    return {
        "dense_similarity": dense,
        "keyword_overlap": overlap,
        "keyword_score": keyword_score,
        "graph_bonus": graph_bonus,
        "relevance_score": relevance,
        "recency_score": recency,
        "importance_score": importance,
        "combined_score": combined,
        "passes_relevance": (
            dense >= config.minimum_relevance_score
            or overlap > 0
            or GRAPH_ROUTE in route_hits
        ),
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
    """Return active or optionally archived records.

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


def _route_limit(record_count: int, k: int, config: MemoryConfig) -> int:
    """Return a bounded per-route candidate limit.

    输入:
        record_count: 可检索记录数量。
        k: Top-K 主结果数量。
        config: MemoryConfig 配置对象。
    输出:
        int: 当前路由候选上限。
    示例:
        示例输入: _route_limit(100, 8, config)
        示例输出: 64
    """
    return min(
        record_count,
        max(k, k * config.retrieval_candidate_multiplier * 4),
    )


def _record_scopes(records: Sequence[EpisodicMemory]) -> List[str]:
    """Return scope IDs represented by records, in deterministic order.

    必须排序返回：调用方按此顺序把分数累加进同一个 dict，而后续排序是稳定
    排序，并列项的名次由插入顺序决定。set 的迭代序随进程哈希种子变化，会让
    同输入在不同进程产出不同排名。

    输入:
        records: L2 记录集合。
    输出:
        list[str]: 升序去重的 scope_id 列表。
    示例:
        示例输入: _record_scopes([memory])
        示例输出: ["scope"]
    """
    return sorted({memory.scope_id for memory in records})


def _routes_payload(route_results: Sequence[RouteResult]) -> Dict[str, Dict[str, Any]]:
    """Serialize route-level diagnostics.

    输入:
        route_results: 路由结果列表。
    输出:
        dict: route 到统计信息的映射。
    示例:
        示例输入: _routes_payload([route_result])
        示例输出: {"vector": {"candidate_count": 1, ...}}
    """
    return {
        result.route: {
            "engine": result.engine,
            "candidate_count": len(result.candidates),
            "mem_ids": [candidate.mem_id for candidate in result.candidates],
        }
        for result in route_results
    }


def _result_payload(candidate: FusedCandidate) -> Dict[str, Any]:
    """Serialize a fused candidate for search results.

    输入:
        candidate: 融合后的候选。
    输出:
        dict: 可 JSON 序列化的主结果。
    示例:
        示例输入: _result_payload(candidate)
        示例输出: {"mem_id": "m1", "combined_score": 0.8, ...}
    """
    memory = candidate.memory
    return {
        "mem_id": memory.mem_id,
        "scope_id": memory.scope_id,
        "text": memory.text,
        "status": memory.status.value,
        "importance": memory.importance,
        "fts_score": candidate.route_scores.get(KEYWORD_ROUTE, 0.0),
        "rrf_score": candidate.rrf_score,
        "combined_score": candidate.combined_score,
        "rerank_score": candidate.rerank_score,
        "route_hits": candidate.route_hits,
        "route_scores": candidate.route_scores,
        "route_ranks": candidate.route_ranks,
        "scores": candidate.scores,
    }


def _related_payload(
    candidate: RetrievalCandidate,
    records: Sequence[EpisodicMemory],
) -> Dict[str, Any]:
    """Serialize a graph-expanded related candidate.

    输入:
        candidate: related 路由候选。
        records: 可检索 L2 记录。
    输出:
        dict: 可 JSON 序列化的 related 结果。
    示例:
        示例输入: _related_payload(candidate, [memory])
        示例输出: {"mem_id": "m2", "related_score": 0.5, ...}
    """
    by_id = {memory.mem_id: memory for memory in records}
    memory = by_id[candidate.mem_id]
    return {
        "mem_id": memory.mem_id,
        "scope_id": memory.scope_id,
        "text": memory.text,
        "status": memory.status.value,
        "importance": memory.importance,
        "related_score": candidate.score,
        "route": candidate.route,
        "engine": candidate.engine,
        "metadata": candidate.metadata,
    }


def _node_id(node: Any) -> str:
    """Return a graph node ID from an object or mapping.

    输入:
        node: GraphNode 或序列化节点。
    输出:
        str: 节点 ID。
    示例:
        示例输入: _node_id({"id": "n1"})
        示例输出: "n1"
    """
    return str(getattr(node, "node_id", _mapping_value(node, "id", "")))


def _node_label(node: Any) -> str:
    """Return a graph node label from an object or mapping.

    输入:
        node: GraphNode 或序列化节点。
    输出:
        str: 节点 label。
    示例:
        示例输入: _node_label({"label": "Agent"})
        示例输出: "Agent"
    """
    return str(getattr(node, "label", _mapping_value(node, "label", "")))


def _node_scope_id(node: Any) -> str:
    """Return a graph node scope ID.

    输入:
        node: GraphNode 或序列化节点。
    输出:
        str: scope_id。
    示例:
        示例输入: _node_scope_id({"scope_id": "s"})
        示例输出: "s"
    """
    return str(getattr(node, "scope_id", _mapping_value(node, "scope_id", "")))


def _node_salience(node: Any) -> float:
    """Return graph node salience.

    输入:
        node: GraphNode 或序列化节点。
    输出:
        float: 节点显著度。
    示例:
        示例输入: _node_salience({"salience": 0.5})
        示例输出: 0.5
    """
    return float(getattr(node, "salience", _mapping_value(node, "salience", 0.0)))


def _node_evidence_ids(node: Any) -> List[str]:
    """Return evidence IDs attached to a graph node.

    输入:
        node: GraphNode 或序列化节点。
    输出:
        list[str]: evidence_ids。
    示例:
        示例输入: _node_evidence_ids({"evidence_ids": ["m1"]})
        示例输出: ["m1"]
    """
    evidence_ids = getattr(
        node,
        "evidence_ids",
        _mapping_value(node, "evidence_ids", []),
    )
    return [str(item) for item in evidence_ids]


def _edge_source_id(edge: Any) -> str:
    """Return graph edge source ID.

    输入:
        edge: GraphEdge 或序列化边。
    输出:
        str: source node ID。
    示例:
        示例输入: _edge_source_id({"source": "a"})
        示例输出: "a"
    """
    return str(getattr(edge, "source_id", _mapping_value(edge, "source", "")))


def _edge_target_id(edge: Any) -> str:
    """Return graph edge target ID.

    输入:
        edge: GraphEdge 或序列化边。
    输出:
        str: target node ID。
    示例:
        示例输入: _edge_target_id({"target": "b"})
        示例输出: "b"
    """
    return str(getattr(edge, "target_id", _mapping_value(edge, "target", "")))


def _edge_scope_id(edge: Any) -> str:
    """Return graph edge scope ID.

    输入:
        edge: GraphEdge 或序列化边。
    输出:
        str: scope_id。
    示例:
        示例输入: _edge_scope_id({"scope_id": "s"})
        示例输出: "s"
    """
    return str(getattr(edge, "scope_id", _mapping_value(edge, "scope_id", "")))


def _edge_weight(edge: Any) -> float:
    """Return graph edge weight.

    输入:
        edge: GraphEdge 或序列化边。
    输出:
        float: 边权重。
    示例:
        示例输入: _edge_weight({"weight": 0.7})
        示例输出: 0.7
    """
    return float(getattr(edge, "weight", _mapping_value(edge, "weight", 0.0)))


def _mapping_value(item: Any, key: str, default: Any) -> Any:
    """Read a value from a mapping-like item.

    输入:
        item: 任意对象。
        key: 字段名。
        default: 缺省值。
    输出:
        Any: mapping 值或缺省值。
    示例:
        示例输入: _mapping_value({"a": 1}, "a", 0)
        示例输出: 1
    """
    if isinstance(item, Mapping):
        return item.get(key, default)
    return default
