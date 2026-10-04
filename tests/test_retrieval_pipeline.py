"""Tests for the hybrid retrieval pipeline."""

from __future__ import annotations

import sqlite3
from typing import Any, List, Optional

import mem.retrieval.global_search as global_search
from mem.config.settings import MemoryConfig
from mem.embedding.vector import embed_text
from mem.graph.cognitive import CognitiveGraph
from mem.memory.models import EdgeType, EpisodicMemory, MemoryStatus, NodeType
from mem.retrieval.global_search import KEYWORD_FALLBACK_ENGINE
from mem.retrieval.pipeline import (
    GRAPH_ROUTE,
    HYBRID_RRF_ENGINE,
    HybridSearchPipeline,
    LocalGraphRetriever,
    LocalKeywordRetriever,
    LocalVectorRetriever,
)


def _memory(
    mem_id: str,
    text: str,
    config: MemoryConfig,
    importance: int = 5,
    status: MemoryStatus = MemoryStatus.ACTIVE,
) -> EpisodicMemory:
    """Create a deterministic episodic memory for retrieval tests.

    输入:
        mem_id: 记忆 ID。
        text: 记忆正文。
        config: MemoryConfig 配置对象。
        importance: 重要性分。
        status: 记忆状态。
    输出:
        EpisodicMemory: 可用于检索测试的 L2 记录。
    示例:
        示例输入: _memory("m1", "agent memory", MemoryConfig())
        示例输出: EpisodicMemory(mem_id="m1", ...)
    """
    return EpisodicMemory(
        mem_id=mem_id,
        embedding=embed_text(text, config.embedding_dimensions),
        text=text,
        importance=importance,
        ts_create=1_000.0,
        ts_last_access=1_000.0,
        scope_id="scope",
        status=status,
    )


def _pipeline(
    config: MemoryConfig,
    graph: Optional[CognitiveGraph] = None,
) -> HybridSearchPipeline:
    """Create a local hybrid pipeline for tests.

    输入:
        config: MemoryConfig 配置对象。
        graph: 可选 CognitiveGraph。
    输出:
        HybridSearchPipeline: 本地三路检索流水线。
    示例:
        示例输入: _pipeline(MemoryConfig())
        示例输出: HybridSearchPipeline(...)
    """
    return HybridSearchPipeline(
        config=config,
        retrievers=[
            LocalVectorRetriever(),
            LocalKeywordRetriever(global_search._fts5_matches),
            LocalGraphRetriever(graph=graph),
        ],
    )


def test_pipeline_fuses_three_routes_and_expands_related() -> None:
    """Verify vector, keyword, graph RRF fusion and related expansion.

    输入:
        无；测试内部构造 L2 记录和 L4 图谱。
    输出:
        None；断言三路召回、RRF 和 related 行为。
    示例:
        示例输入: pytest tests/test_retrieval_pipeline.py::test_pipeline_fuses...
        示例输出: 测试通过。
    """
    config = MemoryConfig()
    records: List[EpisodicMemory] = [
        _memory("m_main", "alpha project launch plan", config, importance=8),
        _memory("m_keyword", "alpha compliance checklist", config, importance=6),
        _memory("m_graph", "budget review timeline", config, importance=7),
        _memory("m_related", "downstream owner details", config, importance=5),
    ]
    graph = CognitiveGraph(config)
    graph.add_insight(
        "scope",
        "compliance graph",
        evidence_ids=["m_graph"],
        salience=0.9,
    )
    main_node = graph._upsert_node(
        "scope",
        "alpha project",
        NodeType.INSIGHT,
        ["m_main"],
        0.9,
    )
    related_node = graph._upsert_node(
        "scope",
        "owner relationship",
        NodeType.INSIGHT,
        ["m_related"],
        0.8,
    )
    graph._upsert_edge(
        "scope",
        main_node.node_id,
        related_node.node_id,
        EdgeType.SIMILAR,
        0.8,
    )

    payload = _pipeline(config, graph).search(
        records,
        "alpha compliance",
        k=3,
        now_ts=1_000.0,
    )

    assert payload["engine"] == HYBRID_RRF_ENGINE
    assert payload["routes"]["vector"]["candidate_count"] >= 1
    assert payload["routes"]["keyword"]["candidate_count"] >= 1
    assert payload["routes"]["graph"]["candidate_count"] >= 1
    assert any(
        result["mem_id"] == "m_graph" and GRAPH_ROUTE in result["route_hits"]
        for result in payload["results"]
    )
    assert {item["mem_id"] for item in payload["related"]} == {"m_related"}


def test_pipeline_filters_archived_and_handles_empty_query() -> None:
    """Verify archived filtering and empty-query boundary behavior.

    输入:
        无；测试内部构造 active 与 archived 记录。
    输出:
        None；断言 include_archived 与空查询语义。
    示例:
        示例输入: pytest tests/test_retrieval_pipeline.py::test_pipeline_filters...
        示例输出: 测试通过。
    """
    config = MemoryConfig()
    active = _memory("m_active", "active archive signal", config)
    archived = _memory(
        "m_archived",
        "archived route signal",
        config,
        status=MemoryStatus.ARCHIVED,
    )
    nodes = [
        {
            "id": "n1",
            "label": "archived route",
            "scope_id": "scope",
            "salience": 0.9,
            "evidence_ids": ["m_archived"],
        }
    ]
    pipeline = HybridSearchPipeline(
        config=config,
        retrievers=[
            LocalVectorRetriever(),
            LocalKeywordRetriever(global_search._fts5_matches),
            LocalGraphRetriever(nodes=nodes),
        ],
    )

    without_archived = pipeline.search(
        [active, archived],
        "archived route",
        k=5,
        now_ts=1_000.0,
    )
    with_archived = pipeline.search(
        [active, archived],
        "archived route",
        k=5,
        include_archived=True,
        now_ts=1_000.0,
    )
    empty = pipeline.search([active], "   ", k=5, now_ts=1_000.0)

    assert all(
        result["mem_id"] != "m_archived"
        for result in without_archived["results"]
    )
    assert any(result["mem_id"] == "m_archived" for result in with_archived["results"])
    assert empty["results"] == []
    assert empty["related"] == []


def test_pipeline_reranker_failure_falls_back() -> None:
    """Verify reranker adapter failures fall back to composite-score ordering.

    输入:
        无；测试内部构造失败 reranker。
    输出:
        None；断言检索仍返回结果并记录 rerank_error。
    示例:
        示例输入: pytest tests/test_retrieval_pipeline.py::test_pipeline_reranker...
        示例输出: 测试通过。
    """

    class FailingReranker:
        """Reranker test double that raises an exception."""

        def rerank(self, candidates: Any, request: Any, k: int) -> Any:
            """Raise to exercise fallback behavior.

            输入:
                candidates: 待重排候选。
                request: 标准化检索请求。
                k: 返回数量。
            输出:
                不返回；总是抛出 RuntimeError。
            示例:
                示例输入: FailingReranker().rerank([], request, 1)
                示例输出: RuntimeError
            """
            raise RuntimeError("reranker unavailable")

    config = MemoryConfig()
    memory = _memory("m1", "rerank fallback memory", config)
    pipeline = HybridSearchPipeline(
        config=config,
        retrievers=[
            LocalVectorRetriever(),
            LocalKeywordRetriever(global_search._fts5_matches),
        ],
        reranker=FailingReranker(),
    )

    payload = pipeline.search([memory], "rerank", k=1, now_ts=1_000.0)

    assert payload["results"][0]["mem_id"] == "m1"
    assert payload["rerank_error"] == "reranker unavailable"


def test_global_search_uses_keyword_fallback_when_fts5_unavailable(
    monkeypatch: Any,
) -> None:
    """Verify global search exposes keyword fallback diagnostics.

    输入:
        monkeypatch: pytest monkeypatch fixture。
    输出:
        None；断言 SQLite FTS5 失败时降级到 keyword fallback。
    示例:
        示例输入: pytest tests/test_retrieval_pipeline.py::test_global_search_uses...
        示例输出: 测试通过。
    """

    def raise_sqlite_error(*args: Any, **kwargs: Any) -> Any:
        """Raise sqlite3.Error for monkeypatched connect.

        输入:
            args: 任意位置参数。
            kwargs: 任意关键字参数。
        输出:
            不返回；总是抛出 sqlite3.Error。
        示例:
            示例输入: raise_sqlite_error()
            示例输出: sqlite3.Error
        """
        raise sqlite3.Error("fts5 unavailable")

    config = MemoryConfig()
    memory = _memory("m1", "fallback needle memory", config)
    monkeypatch.setattr(global_search.sqlite3, "connect", raise_sqlite_error)

    payload = global_search.fts5_global_semantic_search(
        [memory],
        "needle",
        config,
        k=1,
        now_ts=1_000.0,
    )

    assert payload["keyword_engine"] == KEYWORD_FALLBACK_ENGINE
    assert payload["fts_match_count"] == 1
    assert payload["results"][0]["mem_id"] == "m1"
