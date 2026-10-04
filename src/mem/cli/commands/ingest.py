"""CLI command for converting external messages into stored memories."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

from ..context import build_context, finalize_payload
from ..message_ingest import (
    INPUT_FORMAT_CHOICES,
    OUTPUT_FORMAT_CHOICES,
    ROLE_CHOICES,
    STORE_MODE_CHOICES,
    ParsedMessage,
    format_messages,
    parse_messages,
)
from ..result import CliError, CliResult, result


def register_ingest_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register message ingestion commands.

    Example Input:
        register_ingest_commands(subparsers)
    Example Output:
        The parser accepts `mem ingest`.
    """
    ingest = subparsers.add_parser(
        "ingest",
        help="Convert stdin or file messages into memories and store them.",
    )
    ingest.add_argument(
        "-i",
        "--input",
        dest="input_path",
        help="Input file path. Omit to read from stdin.",
    )
    ingest.add_argument(
        "--input-format",
        choices=INPUT_FORMAT_CHOICES,
        default="auto",
        help="Input parser: auto, text, json, or jsonl.",
    )
    ingest.add_argument(
        "--default-role",
        choices=ROLE_CHOICES,
        default="user",
        help="Role assigned to text lines or JSON items without role.",
    )
    ingest.add_argument(
        "--store-as",
        choices=STORE_MODE_CHOICES,
        default="observe",
        help="Storage mode: observe writes L0, memorize writes L2, none only converts.",
    )
    ingest.add_argument(
        "--importance",
        type=int,
        help="Explicit importance for --store-as memorize.",
    )
    ingest.add_argument(
        "-o",
        "--output",
        dest="output_path",
        help="Optional file path for converted memories.",
    )
    ingest.add_argument(
        "--output-format",
        choices=OUTPUT_FORMAT_CHOICES,
        default="json",
        help="Converted memories output format.",
    )
    ingest.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output files and inline payloads.",
    )
    ingest.set_defaults(handler=handle_ingest)


def handle_ingest(args: Any) -> CliResult:
    """Handle `mem ingest`.

    Example Input:
        handle_ingest(args_for_stdin_text)
    Example Output:
        CliResult(command="ingest", payload={"count": 2, ...})
    """
    raw_text, source = _read_input(args.input_path)
    messages = parse_messages(
        raw_text,
        input_format=args.input_format,
        default_role=args.default_role,
        source=source,
    )
    context = build_context(args)
    converted = [
        message.to_memory_dict(context.session_id, context.scope_id)
        for message in messages
    ]
    store_results = _store_messages(
        messages,
        args.store_as,
        context,
        args.importance,
    )
    payload: Dict[str, Any] = {
        "count": len(messages),
        "stored": len(store_results),
        "store_as": args.store_as,
        "input_source": source,
        "input_format": args.input_format,
        "output_format": args.output_format,
        "session_id": context.session_id,
        "scope_id": context.scope_id,
        "store_results": store_results,
    }
    _attach_converted_output(payload, converted, args)
    return result(
        "ingest",
        finalize_payload(context, payload),
        "messages ingested",
    )


def _read_input(input_path: str) -> tuple[str, str]:
    """Read raw messages from a file or stdin.

    Example Input:
        _read_input("messages.jsonl")
    Example Output:
        ("{...}\\n", "messages.jsonl")
    """
    if input_path:
        path = Path(input_path)
        if not path.exists():
            msg = f"input file does not exist: {input_path}"
            raise CliError(msg)
        if not path.is_file():
            msg = f"input path is not a file: {input_path}"
            raise CliError(msg)
        return path.read_text(encoding="utf-8"), str(path)
    if sys.stdin.isatty():
        msg = "provide --input or pipe message content to stdin."
        raise CliError(msg)
    return sys.stdin.read(), "stdin"


def _store_messages(
    messages: Sequence[ParsedMessage],
    store_as: str,
    context: Any,
    importance: int,
) -> List[Dict[str, Any]]:
    """Store parsed messages through the selected memory write path.

    Example Input:
        _store_messages(messages, "observe", context, None)
    Example Output:
        [{"index": 1, "role": "user", "mem_id": "..."}]
    """
    if store_as == "none":
        return []
    store_results: List[Dict[str, Any]] = []
    for message in messages:
        if store_as == "observe":
            item = context.memory.observe(
                session_id=context.session_id,
                msg=message.to_observe_message(),
                scope_id=context.scope_id,
            )
        elif store_as == "memorize":
            item = context.memory.memorize(
                session_id=context.session_id,
                text=message.content,
                scope_id=context.scope_id,
                importance=importance,
            )
        else:
            msg = f"unsupported storage mode: {store_as}"
            raise CliError(msg)
        store_results.append(_summarize_store_result(message, item))
    return store_results


def _summarize_store_result(
    message: ParsedMessage,
    item: Dict[str, Any],
) -> Dict[str, Any]:
    """Return compact per-message storage diagnostics.

    Example Input:
        _summarize_store_result(message, {"mem_id": "m1"})
    Example Output:
        {"index": 1, "role": "user", "mem_id": "m1"}
    """
    return {
        "index": message.index,
        "role": message.role,
        "mem_id": item.get("mem_id"),
        "promoted": item.get("promoted", []),
        "storage_path": item.get("storage_path"),
    }


def _attach_converted_output(
    payload: Dict[str, Any],
    converted: Sequence[Dict[str, Any]],
    args: Any,
) -> None:
    """Attach converted memories inline or write them to an output file.

    Example Input:
        _attach_converted_output(payload, converted, args_with_output_path)
    Example Output:
        payload["output_path"] is set when an output file is requested.
    """
    rendered = format_messages(converted, args.output_format, pretty=args.pretty)
    if not args.output_path:
        payload["memories"] = list(converted)
        return
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    payload["output_path"] = str(output_path)
