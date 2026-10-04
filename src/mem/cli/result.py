"""Shared CLI result and error helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, TextIO


class CliError(Exception):
    """User-facing CLI error."""


@dataclass
class CliResult:
    """Structured result emitted by one CLI command.

    输入:
        ok: 命令是否成功。
        command: 命令名称。
        payload: JSON-compatible 命令结果。
        message: 可读提示信息。
    输出:
        CliResult: 可序列化的 CLI 命令结果。
    示例:
        示例输入: CliResult(True, "snapshot", {"l2_active": 1})
        示例输出: result.to_dict()["ok"] == True
    """

    ok: bool
    command: str
    payload: Dict[str, Any]
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert the result to a JSON-compatible dictionary.

        输入:
            self: CLI 命令结果。
        输出:
            dict: JSON-compatible result payload。
        示例:
            示例输入: CliResult(True, "help", {}).to_dict()
            示例输出: {"ok": True, "command": "help", ...}
        """
        return {
            "ok": self.ok,
            "command": self.command,
            "message": self.message,
            "payload": self.payload,
        }


def result(command: str, payload: Mapping[str, Any], message: str = "") -> CliResult:
    """Create a successful CLI result.

    输入:
        command: 命令名称。
        payload: 命令输出。
        message: 可读提示信息。
    输出:
        CliResult: 成功结果。
    示例:
        示例输入: result("state", {"exists": True})
        示例输出: CliResult(ok=True, command="state", ...)
    """
    return CliResult(True, command, dict(payload), message)


def dump_result(result_item: CliResult, output: TextIO) -> None:
    """Write one CLI result as pretty JSON.

    输入:
        result_item: CLI 命令结果。
        output: 输出流。
    输出:
        None。
    示例:
        示例输入: dump_result(CliResult(True, "state", {}), sys.stdout)
        示例输出: stdout 写入 JSON。
    """
    output.write(json.dumps(result_item.to_dict(), ensure_ascii=False, indent=2))
    output.write("\n")
    output.flush()
