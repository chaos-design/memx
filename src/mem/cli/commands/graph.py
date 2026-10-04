"""L4 graph CLI commands."""

from __future__ import annotations

import argparse
from typing import Any

from ..context import build_context, finalize_payload
from ..parsing import join_words
from ..result import CliResult, result


def register_graph_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register graph inspection and audit commands.

    输入:
        subparsers: argparse subparser registry。
    输出:
        None。
    示例:
        示例输入: register_graph_commands(subparsers)
        示例输出: graph audit/query 被注册。
    """
    graph = subparsers.add_parser("graph", help="Inspect L4 cognitive graph.")
    graph_subparsers = graph.add_subparsers(dest="graph_command", required=True)

    audit = graph_subparsers.add_parser("audit", help="Audit graph consistency.")
    audit.add_argument("--no-repair", action="store_true")
    audit.set_defaults(handler=handle_graph_audit)

    query = graph_subparsers.add_parser("query", help="Query graph nodes.")
    query.add_argument("query", nargs="*")
    query.add_argument("-k", "--top-k", type=int, default=8)
    query.set_defaults(handler=handle_graph_query)


def handle_graph_audit(args: Any) -> CliResult:
    """Handle `graph audit` command.

    输入:
        args: 包含 no_repair 的 argparse namespace。
    输出:
        CliResult: L4 graph audit 结果。
    示例:
        示例输入: handle_graph_audit(args)
        示例输出: CliResult(command="graph", ...)
    """
    context = build_context(args)
    payload = context.memory.graph_audit(context.scope_id, repair=not args.no_repair)
    if payload.get("removed_edges", 0) > 0:
        context.memory.persistence.mark_dirty(context.scope_id)
    return result("graph", finalize_payload(context, payload), "graph audited")


def handle_graph_query(args: Any) -> CliResult:
    """Handle `graph query` command.

    输入:
        args: 包含 query 与 top_k 的 argparse namespace。
    输出:
        CliResult: L4 graph query 结果。
    示例:
        示例输入: handle_graph_query(args)
        示例输出: CliResult(command="graph", ...)
    """
    context = build_context(args)
    payload = context.memory.l4.graph_query(
        context.scope_id,
        join_words(args.query),
        k=args.top_k,
    )
    return result("graph", payload, "graph query completed")
