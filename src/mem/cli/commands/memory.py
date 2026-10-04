"""Core memory CLI commands."""

from __future__ import annotations

import argparse
from typing import Any

from ...constants import FORGET_MODE_CHOICES
from ..context import (
    build_context,
    finalize_payload,
    summarize_snapshot,
    summarize_state,
)
from ..parsing import join_words
from ..result import CliError, CliResult, result


def register_memory_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register core memory, retrieval, and persistence commands.

    输入:
        subparsers: argparse subparser registry。
    输出:
        None。
    示例:
        示例输入: register_memory_commands(subparsers)
        示例输出: observe、recall、snapshot 等命令被注册。
    """
    observe = subparsers.add_parser("observe", help="Append one L0 message.")
    observe.add_argument("role", choices=("user", "assistant", "tool", "system"))
    observe.add_argument("content", nargs="+")
    observe.set_defaults(handler=handle_observe)

    memorize = subparsers.add_parser("memorize", help="Promote explicit L2 memory.")
    memorize.add_argument("text", nargs="+")
    memorize.add_argument("--importance", type=int)
    memorize.set_defaults(handler=handle_memorize)

    recall = subparsers.add_parser("recall", help="Recall facts and episodes.")
    recall.add_argument("query", nargs="+")
    recall.add_argument("-k", "--top-k", type=int, default=8)
    recall.add_argument("--entity", action="append", default=[])
    recall.add_argument("--active-only", action="store_true")
    recall.set_defaults(handler=handle_recall)

    search = subparsers.add_parser("search", help="Search active memory only.")
    search.add_argument("query", nargs="+")
    search.add_argument("-k", "--top-k", type=int, default=8)
    search.set_defaults(handler=handle_search)

    context = subparsers.add_parser("context", help="Render prompt-ready context.")
    context.add_argument("query", nargs="*")
    context.set_defaults(handler=handle_context)

    reflect = subparsers.add_parser("reflect", help="Consolidate L2 into L3/L4.")
    reflect.add_argument("--force", action="store_true")
    reflect.set_defaults(handler=handle_reflect)

    forget = subparsers.add_parser("forget", help="Run a forgetting mode.")
    forget.add_argument("mode", choices=FORGET_MODE_CHOICES)
    forget.add_argument("mem_id", nargs="?")
    forget.add_argument("--force", action="store_true")
    forget.set_defaults(handler=handle_forget)

    snapshot = subparsers.add_parser("snapshot", help="Show L0-L4 architecture state.")
    snapshot.add_argument("--full", action="store_true")
    snapshot.set_defaults(handler=handle_snapshot)

    state = subparsers.add_parser("state", help="Read persisted scope state.")
    state.set_defaults(handler=handle_state)

    flush = subparsers.add_parser("flush", help="Persist current scope state.")
    flush.set_defaults(handler=handle_flush)

    diagnostics = subparsers.add_parser(
        "diagnostics",
        help="Show backend adapter diagnostics.",
    )
    diagnostics.set_defaults(handler=handle_diagnostics)


def handle_observe(args: Any) -> CliResult:
    """Handle `observe` command.

    输入:
        args: 包含 role 与 content 的 argparse namespace。
    输出:
        CliResult: observe 结果。
    示例:
        示例输入: handle_observe(args)
        示例输出: CliResult(command="observe", ...)
    """
    context = build_context(args)
    payload = context.memory.observe(
        session_id=context.session_id,
        msg={"role": args.role, "content": join_words(args.content)},
        scope_id=context.scope_id,
    )
    return result("observe", finalize_payload(context, payload), "message observed")


def handle_memorize(args: Any) -> CliResult:
    """Handle `memorize` command.

    输入:
        args: 包含 text 与 importance 的 argparse namespace。
    输出:
        CliResult: memorize 结果。
    示例:
        示例输入: handle_memorize(args)
        示例输出: CliResult(command="memorize", ...)
    """
    context = build_context(args)
    payload = context.memory.memorize(
        session_id=context.session_id,
        text=join_words(args.text),
        scope_id=context.scope_id,
        importance=args.importance,
    )
    return result("memorize", finalize_payload(context, payload), "memory promoted")


def handle_recall(args: Any) -> CliResult:
    """Handle `recall` command.

    输入:
        args: 包含 query、top_k 与 entity 的 argparse namespace。
    输出:
        CliResult: recall 结果。
    示例:
        示例输入: handle_recall(args)
        示例输出: CliResult(command="recall", ...)
    """
    context = build_context(args)
    payload = context.memory.recall(
        session_id=context.session_id,
        query=join_words(args.query),
        k=args.top_k,
        entities=args.entity or None,
        scope_id=context.scope_id,
        include_archived=not args.active_only,
    )
    return result("recall", finalize_payload(context, payload), "recall completed")


def handle_search(args: Any) -> CliResult:
    """Handle `search` command.

    输入:
        args: 包含 query 与 top_k 的 argparse namespace。
    输出:
        CliResult: search 结果。
    示例:
        示例输入: handle_search(args)
        示例输出: CliResult(command="search", ...)
    """
    context = build_context(args)
    payload = context.memory.search(
        session_id=context.session_id,
        query=join_words(args.query),
        scope_id=context.scope_id,
        k=args.top_k,
    )
    return result("search", finalize_payload(context, payload), "search completed")


def handle_context(args: Any) -> CliResult:
    """Handle `context` command.

    输入:
        args: 包含可选 query 的 argparse namespace。
    输出:
        CliResult: prompt context 结果。
    示例:
        示例输入: handle_context(args)
        示例输出: CliResult(payload={"context": "...", "chars": 10})
    """
    context = build_context(args)
    text = context.memory.get_context(
        session_id=context.session_id,
        query=join_words(args.query) if args.query else None,
        scope_id=context.scope_id,
    )
    payload = finalize_payload(context, {"context": text, "chars": len(text)})
    return result("context", payload, "context rendered")


def handle_reflect(args: Any) -> CliResult:
    """Handle `reflect` command.

    输入:
        args: 包含 force 的 argparse namespace。
    输出:
        CliResult: reflect 结果。
    示例:
        示例输入: handle_reflect(args)
        示例输出: CliResult(command="reflect", ...)
    """
    context = build_context(args)
    payload = context.memory.reflect(context.scope_id, force=args.force)
    return result("reflect", finalize_payload(context, payload), "reflection completed")


def handle_forget(args: Any) -> CliResult:
    """Handle `forget` command.

    输入:
        args: 包含 mode、mem_id 与 force 的 argparse namespace。
    输出:
        CliResult: forget 结果。
    示例:
        示例输入: handle_forget(args)
        示例输出: CliResult(command="forget", ...)
    """
    if args.mode == "hard" and not args.mem_id:
        raise CliError("forget hard requires mem_id.")
    context = build_context(args)
    payload = context.memory.forget(
        scope_id=context.scope_id,
        mode=args.mode,
        mem_id=args.mem_id,
        force=args.force,
    )
    return result("forget", finalize_payload(context, payload), "forget completed")


def handle_snapshot(args: Any) -> CliResult:
    """Handle `snapshot` command.

    输入:
        args: 包含 full 的 argparse namespace。
    输出:
        CliResult: architecture snapshot。
    示例:
        示例输入: handle_snapshot(args)
        示例输出: CliResult(command="snapshot", ...)
    """
    context = build_context(args)
    snapshot = context.memory.architecture_snapshot(context.scope_id)
    payload = snapshot if args.full else summarize_snapshot(snapshot)
    if context.loaded_state:
        payload = dict(payload)
        payload["loaded_state"] = context.loaded_state
    return result("snapshot", payload, "snapshot loaded")


def handle_state(args: Any) -> CliResult:
    """Handle `state` command.

    输入:
        args: argparse namespace。
    输出:
        CliResult: persisted state summary。
    示例:
        示例输入: handle_state(args)
        示例输出: CliResult(command="state", ...)
    """
    context = build_context(args)
    state = context.memory.read_stored_state(context.scope_id)
    payload = summarize_state(context.memory, context.scope_id, state)
    return result("state", payload, "state loaded")


def handle_flush(args: Any) -> CliResult:
    """Handle `flush` command.

    输入:
        args: argparse namespace。
    输出:
        CliResult: flush 路径。
    示例:
        示例输入: handle_flush(args)
        示例输出: CliResult(payload={"storage_path": ".memories/..."})
    """
    context = build_context(args)
    storage_path = context.memory.flush(context.scope_id)
    return result("flush", {"storage_path": storage_path}, "scope state flushed")


def handle_diagnostics(args: Any) -> CliResult:
    """Handle `diagnostics` command.

    输入:
        args: argparse namespace。
    输出:
        CliResult: backend diagnostics。
    示例:
        示例输入: handle_diagnostics(args)
        示例输出: CliResult(command="diagnostics", ...)
    """
    context = build_context(args)
    return result(
        "diagnostics",
        context.memory.backend_diagnostics(),
        "backend diagnostics loaded",
    )
