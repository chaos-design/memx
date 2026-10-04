"""Configuration CLI commands."""

from __future__ import annotations

import argparse
from typing import Any

from ...config import read_hms_config, write_hms_config
from ..context import load_cli_config
from ..parsing import config_to_dict, parse_key_value_updates
from ..result import CliResult, result


def register_config_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register hms.json configuration commands.

    输入:
        subparsers: argparse subparser registry。
    输出:
        None。
    示例:
        示例输入: register_config_commands(subparsers)
        示例输出: config show/set 被注册。
    """
    config = subparsers.add_parser("config", help="Read or update hms.json.")
    config_subparsers = config.add_subparsers(dest="config_command", required=True)

    show = config_subparsers.add_parser("show", help="Show configuration.")
    show.add_argument("--effective", action="store_true")
    show.set_defaults(handler=handle_config_show)

    set_config = config_subparsers.add_parser("set", help="Patch configuration.")
    set_config.add_argument("updates", nargs="+", metavar="KEY=VALUE")
    set_config.set_defaults(handler=handle_config_set)


def handle_config_show(args: Any) -> CliResult:
    """Handle `config show` command.

    输入:
        args: 包含 effective 的 argparse namespace。
    输出:
        CliResult: hms.json 或有效配置。
    示例:
        示例输入: handle_config_show(args)
        示例输出: CliResult(command="config", ...)
    """
    if args.effective:
        payload = config_to_dict(load_cli_config(args))
        message = "effective configuration loaded"
    else:
        payload = read_hms_config(args.config_path)
        message = "hms.json loaded"
    return result("config", payload, message)


def handle_config_set(args: Any) -> CliResult:
    """Handle `config set` command.

    输入:
        args: 包含 KEY=VALUE updates 的 argparse namespace。
    输出:
        CliResult: 更新后的 hms.json。
    示例:
        示例输入: handle_config_set(args)
        示例输出: CliResult(command="config", ...)
    """
    updates = parse_key_value_updates(args.updates)
    payload = write_hms_config(updates, args.config_path)
    return result("config", payload, "hms.json updated")
