"""Update CLI commands for L2 memories and L3 facts."""

from __future__ import annotations

import argparse
from typing import Any, Dict

from ...models import MemoryType
from ..context import build_context, finalize_payload
from ..parsing import join_words
from ..result import CliError, CliResult, result


def register_update_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register L2/L3 update commands.

    输入:
        subparsers: argparse subparser registry。
    输出:
        None。
    示例:
        示例输入: register_update_commands(subparsers)
        示例输出: update fact 与 update mem 被注册。
    """
    update = subparsers.add_parser("update", help="Update a fact or L2 memory.")
    update_subparsers = update.add_subparsers(dest="update_target", required=True)

    fact = update_subparsers.add_parser("fact", help="Upsert an L3 fact.")
    fact.add_argument("fact_key")
    fact.add_argument("value", nargs="+")
    fact.add_argument("--confidence", type=float, default=0.9)
    fact.add_argument("--partition")
    fact.add_argument(
        "--mem-type",
        choices=[item.value for item in MemoryType],
        default=MemoryType.SEMANTIC.value,
    )
    fact.set_defaults(handler=handle_update_fact)

    memory = update_subparsers.add_parser("mem", help="Update an L2 memory.")
    memory.add_argument("mem_id")
    memory.add_argument("text", nargs="*")
    memory.add_argument("--importance", type=int)
    memory.set_defaults(handler=handle_update_memory)


def handle_update_fact(args: Any) -> CliResult:
    """Handle `update fact` command.

    输入:
        args: 包含 fact_key、value 与 confidence 的 argparse namespace。
    输出:
        CliResult: fact update 结果。
    示例:
        示例输入: handle_update_fact(args)
        示例输出: CliResult(command="update", ...)
    """
    context = build_context(args)
    payload: Dict[str, Any] = {
        "scope_id": context.scope_id,
        "fact_key": args.fact_key,
        "value": join_words(args.value),
        "confidence": args.confidence,
        "mem_type": args.mem_type,
    }
    if args.partition:
        payload["partition"] = args.partition
    updated = context.memory.update(payload)
    return result("update", finalize_payload(context, updated), "fact updated")


def handle_update_memory(args: Any) -> CliResult:
    """Handle `update mem` command.

    输入:
        args: 包含 mem_id、text 与 importance 的 argparse namespace。
    输出:
        CliResult: memory update 结果。
    示例:
        示例输入: handle_update_memory(args)
        示例输出: CliResult(command="update", ...)
    """
    if not args.text and args.importance is None:
        raise CliError("update mem requires text or --importance.")
    context = build_context(args)
    payload: Dict[str, Any] = {"scope_id": context.scope_id, "mem_id": args.mem_id}
    if args.text:
        payload["text"] = join_words(args.text)
    if args.importance is not None:
        payload["importance"] = args.importance
    updated = context.memory.update(payload)
    return result("update", finalize_payload(context, updated), "memory updated")
