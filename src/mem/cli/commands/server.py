"""HTTP server CLI command."""

from __future__ import annotations

import argparse
from typing import Any

from ..result import CliResult, result


def register_server_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register HTTP server command.

    输入:
        subparsers: argparse subparser registry。
    输出:
        None。
    示例:
        示例输入: register_server_commands(subparsers)
        示例输出: serve 命令被注册。
    """
    serve = subparsers.add_parser("serve", help="Run the FastAPI server.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(handler=handle_serve)


def handle_serve(args: Any) -> CliResult:
    """Handle `serve` command.

    输入:
        args: 包含 host、port 与 log_level 的 argparse namespace。
    输出:
        CliResult: server stopped 后的摘要。
    示例:
        示例输入: handle_serve(args)
        示例输出: CliResult(command="serve", ...)
    """
    import uvicorn

    from ...server.app import create_app

    app = create_app(config_path=args.config_path)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return result(
        "serve",
        {"host": args.host, "port": args.port},
        "server stopped",
    )
