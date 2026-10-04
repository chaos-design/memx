"""Maintenance CLI commands."""

from __future__ import annotations

import argparse
from typing import Any

from ...scheduler import MaintenanceTaskManager, supported_tasks
from ..context import build_context, finalize_payload
from ..result import CliResult, result


def register_maintenance_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register maintenance scheduler commands.

    输入:
        subparsers: argparse subparser registry。
    输出:
        None。
    示例:
        示例输入: register_maintenance_commands(subparsers)
        示例输出: maintenance run/status 被注册。
    """
    maintenance = subparsers.add_parser(
        "maintenance",
        help="Run or inspect scheduled maintenance tasks.",
    )
    maintenance_subparsers = maintenance.add_subparsers(
        dest="maintenance_command",
        required=True,
    )

    run = maintenance_subparsers.add_parser("run", help="Run maintenance once.")
    run.add_argument("tasks", nargs="*", choices=supported_tasks())
    run.add_argument("--force-reflect", action="store_true")
    run.set_defaults(handler=handle_maintenance_run)

    status = maintenance_subparsers.add_parser(
        "status",
        help="Show registered maintenance task state.",
    )
    status.set_defaults(handler=handle_maintenance_status)


def handle_maintenance_run(args: Any) -> CliResult:
    """Handle `maintenance run` command.

    输入:
        args: 包含 tasks 与 force_reflect 的 argparse namespace。
    输出:
        CliResult: maintenance 执行结果。
    示例:
        示例输入: handle_maintenance_run(args)
        示例输出: CliResult(command="maintenance", ...)
    """
    context = build_context(args)
    manager = MaintenanceTaskManager(context.memory, scope_id=context.scope_id)
    payload = manager.run_once(
        tasks=args.tasks or None,
        force_reflect=args.force_reflect,
    )
    return result(
        "maintenance",
        finalize_payload(context, payload),
        "maintenance completed",
    )


def handle_maintenance_status(args: Any) -> CliResult:
    """Handle `maintenance status` command.

    输入:
        args: argparse namespace。
    输出:
        CliResult: maintenance status。
    示例:
        示例输入: handle_maintenance_status(args)
        示例输出: CliResult(command="maintenance", ...)
    """
    context = build_context(args)
    manager = MaintenanceTaskManager(context.memory, scope_id=context.scope_id)
    return result("maintenance", manager.status(), "maintenance status")
