"""Top-level parser and process entry point for MemX CLI."""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from ..constants import PROJECT_MEMORY_SCOPE_ID
from .commands import (
    register_config_commands,
    register_graph_commands,
    register_ingest_commands,
    register_maintenance_commands,
    register_memory_commands,
    register_retrieval_commands,
    register_server_commands,
    register_update_commands,
)
from .result import CliResult, dump_result

DEFAULT_SESSION_ID = "cli-session"


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the MemX CLI entry point.

    输入:
        argv: 可选命令行参数；None 表示读取 sys.argv。
    输出:
        int: 进程退出码；成功为 0。
    示例:
        示例输入: main(["snapshot"])
        示例输出: 0
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except KeyboardInterrupt:
        result = CliResult(False, args.command_name, {}, "interrupted")
        dump_result(result, sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI must report errors, not crash.
        result = CliResult(
            False,
            getattr(args, "command_name", "mem"),
            {"error_type": type(exc).__name__},
            str(exc),
        )
        dump_result(result, sys.stderr)
        return 1
    if result is not None:
        dump_result(result, sys.stdout)
        return 0 if result.ok else 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser and register all subcommands.

    输入:
        无。
    输出:
        argparse.ArgumentParser: 已注册子命令的 parser。
    示例:
        示例输入: build_parser().parse_args(["snapshot"])
        示例输出: Namespace(command_name="snapshot", ...)
    """
    parser = argparse.ArgumentParser(
        prog="mem",
        description="MemX command line interface.",
    )
    parser.add_argument("--config", dest="config_path", help="Path to hms.json.")
    parser.add_argument(
        "--memory-dir",
        help="Project-relative .memories directory override.",
    )
    parser.add_argument(
        "--session-id",
        default=DEFAULT_SESSION_ID,
        help="Default session id for session-scoped commands.",
    )
    parser.add_argument(
        "--scope-id",
        default=PROJECT_MEMORY_SCOPE_ID,
        help="Memory scope id used by CLI commands.",
    )
    parser.add_argument(
        "--backend-mode",
        choices=("memory", "production"),
        help="Override backend mode from configuration.",
    )
    persist_group = parser.add_mutually_exclusive_group()
    persist_group.add_argument(
        "--persist-on-write",
        dest="persist_on_write",
        action="store_true",
        help="Persist state after write-side operations.",
    )
    persist_group.add_argument(
        "--no-persist-on-write",
        dest="persist_on_write",
        action="store_false",
        help="Disable service-level write persistence.",
    )
    parser.set_defaults(persist_on_write=None)
    parser.add_argument(
        "--no-load-state",
        action="store_true",
        help="Do not hydrate memory-mode adapters from stored snapshots.",
    )

    subparsers = parser.add_subparsers(dest="command_name", required=True)
    register_memory_commands(subparsers)
    register_ingest_commands(subparsers)
    register_update_commands(subparsers)
    register_maintenance_commands(subparsers)
    register_graph_commands(subparsers)
    register_retrieval_commands(subparsers)
    register_config_commands(subparsers)
    register_server_commands(subparsers)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
