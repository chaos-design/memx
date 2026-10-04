"""Retrieval diagnostics CLI commands."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List, Mapping

from ...memory.models import EpisodicMemory
from ...retrieval.global_search import (
    fts5_global_semantic_search,
    hybrid_rerank_diagnostics,
    keyword_rank_records,
    relevance_diagnostics,
)
from ..context import build_context, iter_scope_states, snapshot_records
from ..parsing import join_words
from ..result import CliResult, result


def register_retrieval_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register retrieval inspection commands.

    输入:
        subparsers: argparse subparser registry。
    输出:
        None。
    示例:
        示例输入: register_retrieval_commands(subparsers)
        示例输出: retrieval fts5/keywords/rerank/relevance/score 被注册。
    """
    retrieval = subparsers.add_parser(
        "retrieval",
        help="Inspect FTS5, keyword, relevance, score, and rerank logic.",
    )
    retrieval_subparsers = retrieval.add_subparsers(
        dest="retrieval_command",
        required=True,
    )

    fts5 = retrieval_subparsers.add_parser(
        "fts5",
        help="Run FTS5 global semantic search over stored L2 records.",
    )
    _add_query_args(fts5)
    _add_record_scope_args(fts5)
    fts5.set_defaults(handler=handle_retrieval_fts5)

    search = retrieval_subparsers.add_parser(
        "search",
        help="Alias of retrieval fts5.",
    )
    _add_query_args(search)
    _add_record_scope_args(search)
    search.set_defaults(handler=handle_retrieval_fts5)

    keywords = retrieval_subparsers.add_parser(
        "keywords",
        help="Rank records by sparse keyword overlap.",
    )
    _add_query_args(keywords)
    _add_record_scope_args(keywords)
    keywords.set_defaults(handler=handle_retrieval_keywords)

    rerank = retrieval_subparsers.add_parser(
        "rerank",
        help="Inspect candidate pool, dense/sparse ranks, RRF, and F2 rerank.",
    )
    _add_query_args(rerank)
    _add_record_scope_args(rerank)
    rerank.set_defaults(handler=handle_retrieval_rerank)

    relevance = retrieval_subparsers.add_parser(
        "relevance",
        help="Inspect semantic relevance threshold decisions.",
    )
    _add_query_args(relevance)
    _add_record_scope_args(relevance)
    relevance.add_argument("--mem-id")
    relevance.set_defaults(handler=handle_retrieval_relevance)

    score = retrieval_subparsers.add_parser(
        "score",
        help="Inspect F2 score components.",
    )
    _add_query_args(score)
    _add_record_scope_args(score)
    score.add_argument("--mem-id")
    score.set_defaults(handler=handle_retrieval_score)


def handle_retrieval_fts5(args: Any) -> CliResult:
    """Handle `retrieval fts5` and `retrieval search`.

    输入:
        args: 包含 query、top_k、all_scopes 的 argparse namespace。
    输出:
        CliResult: FTS5 + semantic rerank 搜索结果。
    示例:
        示例输入: handle_retrieval_fts5(args)
        示例输出: CliResult(command="retrieval", ...)
    """
    context = build_context(args)
    records = _records_for_args(context, args)
    payload = fts5_global_semantic_search(
        records,
        join_words(args.query),
        context.memory.config,
        k=args.top_k,
        include_archived=args.include_archived,
        **_graph_kwargs_for_args(context, args),
    )
    payload["scope_mode"] = "all" if args.all_scopes else "current"
    return result("retrieval", payload, "retrieval fts5 completed")


def handle_retrieval_keywords(args: Any) -> CliResult:
    """Handle `retrieval keywords`.

    输入:
        args: 包含 query、top_k、all_scopes 的 argparse namespace。
    输出:
        CliResult: keyword 排序结果。
    示例:
        示例输入: handle_retrieval_keywords(args)
        示例输出: CliResult(command="retrieval", ...)
    """
    context = build_context(args)
    records = _records_for_args(context, args)
    payload = keyword_rank_records(
        records,
        join_words(args.query),
        k=args.top_k,
        include_archived=args.include_archived,
    )
    payload["scope_mode"] = "all" if args.all_scopes else "current"
    return result("retrieval", payload, "retrieval keyword ranking completed")


def handle_retrieval_rerank(args: Any) -> CliResult:
    """Handle `retrieval rerank`.

    输入:
        args: 包含 query、top_k、all_scopes 的 argparse namespace。
    输出:
        CliResult: candidate pool、dense/sparse、RRF、F2 诊断。
    示例:
        示例输入: handle_retrieval_rerank(args)
        示例输出: CliResult(command="retrieval", ...)
    """
    context = build_context(args)
    records = _records_for_args(context, args)
    payload = hybrid_rerank_diagnostics(
        records,
        join_words(args.query),
        context.memory.config,
        k=args.top_k,
        include_archived=args.include_archived,
    )
    payload["scope_mode"] = "all" if args.all_scopes else "current"
    return result("retrieval", payload, "retrieval rerank diagnostics completed")


def handle_retrieval_relevance(args: Any) -> CliResult:
    """Handle `retrieval relevance`.

    输入:
        args: 包含 query、mem_id、top_k 的 argparse namespace。
    输出:
        CliResult: semantic relevance threshold 诊断。
    示例:
        示例输入: handle_retrieval_relevance(args)
        示例输出: CliResult(command="retrieval", ...)
    """
    context = build_context(args)
    records = _records_for_args(context, args)
    payload = relevance_diagnostics(
        records,
        join_words(args.query),
        context.memory.config,
        k=args.top_k,
        include_archived=args.include_archived,
        mem_id=args.mem_id,
    )
    payload["scope_mode"] = "all" if args.all_scopes else "current"
    return result("retrieval", payload, "retrieval relevance diagnostics completed")


def handle_retrieval_score(args: Any) -> CliResult:
    """Handle `retrieval score`.

    输入:
        args: 包含 query、mem_id、top_k 的 argparse namespace。
    输出:
        CliResult: F2 score components。
    示例:
        示例输入: handle_retrieval_score(args)
        示例输出: CliResult(command="retrieval", ...)
    """
    context = build_context(args)
    records = _records_for_args(context, args)
    payload = relevance_diagnostics(
        records,
        join_words(args.query),
        context.memory.config,
        k=args.top_k,
        include_archived=args.include_archived,
        mem_id=args.mem_id,
    )
    payload["score_model"] = "F2"
    payload["scope_mode"] = "all" if args.all_scopes else "current"
    return result("retrieval", payload, "retrieval score diagnostics completed")


def _add_query_args(parser: argparse.ArgumentParser) -> None:
    """Add query and top-k arguments to a retrieval subcommand.

    输入:
        parser: argparse subparser。
    输出:
        None。
    示例:
        示例输入: _add_query_args(parser)
        示例输出: parser 支持 query 与 --top-k。
    """
    parser.add_argument("query", nargs="+")
    parser.add_argument("-k", "--top-k", type=int, default=8)


def _add_record_scope_args(parser: argparse.ArgumentParser) -> None:
    """Add scope selection flags to a retrieval subcommand.

    输入:
        parser: argparse subparser。
    输出:
        None。
    示例:
        示例输入: _add_record_scope_args(parser)
        示例输出: parser 支持 --all-scopes 与 --include-archived。
    """
    parser.add_argument(
        "--all-scopes",
        action="store_true",
        help="Scan all stored scope snapshots under memory_dir.",
    )
    parser.add_argument("--include-archived", action="store_true")


def _records_for_args(context: Any, args: Any) -> List[EpisodicMemory]:
    """Return retrieval records according to CLI flags.

    输入:
        context: CLI runtime context。
        args: argparse namespace。
    输出:
        list[EpisodicMemory]: 检索诊断输入记录。
    示例:
        示例输入: _records_for_args(context, args)
        示例输出: [EpisodicMemory(...)]
    """
    return snapshot_records(context, all_scopes=args.all_scopes)


def _graph_kwargs_for_args(context: Any, args: Any) -> Dict[str, Any]:
    """Return graph inputs for retrieval search according to scope flags.

    输入:
        context: CLI runtime context。
        args: argparse namespace。
    输出:
        dict: 可传入 fts5_global_semantic_search 的图谱参数。
    示例:
        示例输入: _graph_kwargs_for_args(context, args)
        示例输出: {"graph": context.memory.l4}
    """
    if not args.all_scopes:
        return {"graph": context.memory.l4}
    graph_nodes: List[Any] = []
    graph_edges: List[Any] = []
    for state in iter_scope_states(context):
        raw_l4 = state.get("l4", {})
        if not isinstance(raw_l4, Mapping):
            continue
        graph_nodes.extend(raw_l4.get("nodes", []))
        graph_edges.extend(raw_l4.get("edges", []))
    return {"graph_nodes": graph_nodes, "graph_edges": graph_edges}
