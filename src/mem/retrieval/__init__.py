"""Hybrid retrieval helpers for MemX."""

from .candidate_pool import CandidatePoolResult, build_candidate_pool
from .global_search import (
    fts5_global_semantic_search,
    hybrid_rerank_diagnostics,
    keyword_rank_records,
    relevance_diagnostics,
)
from .hybrid import RetrievalOutcome, hybrid_retrieve
from .pipeline import (
    HYBRID_RRF_ENGINE,
    DeterministicCrossEncoderReranker,
    HybridSearchPipeline,
    LocalGraphRetriever,
    LocalKeywordRetriever,
    LocalVectorRetriever,
    RetrievalCandidate,
    RouteResult,
    score_dimensions,
)
from .ranking import hot_candidate_score, keyword_overlap_tokens, rrf_merge

__all__ = [
    "CandidatePoolResult",
    "DeterministicCrossEncoderReranker",
    "HYBRID_RRF_ENGINE",
    "HybridSearchPipeline",
    "LocalGraphRetriever",
    "LocalKeywordRetriever",
    "LocalVectorRetriever",
    "RetrievalCandidate",
    "RetrievalOutcome",
    "RouteResult",
    "build_candidate_pool",
    "fts5_global_semantic_search",
    "hot_candidate_score",
    "hybrid_rerank_diagnostics",
    "hybrid_retrieve",
    "keyword_rank_records",
    "keyword_overlap_tokens",
    "relevance_diagnostics",
    "rrf_merge",
    "score_dimensions",
]
