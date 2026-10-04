"""Command-line updater for MemX hms.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mem.config import default_config_path, write_hms_config  # noqa: E402


def parse_value(value: str) -> Any:
    """Parse a command-line config value.

    输入:
        value: CLI 字符串值。
    输出:
        Any: bool、None、number、JSON 或原始字符串。
    示例:
        示例输入: parse_value("false")
        示例输出: False
    """
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def parse_assignments(assignments: List[str]) -> Dict[str, Any]:
    """Parse repeated key=value assignments.

    输入:
        assignments: `--set` 参数列表。
    输出:
        dict: 配置更新字典。
    示例:
        示例输入: parse_assignments(["max_recall_k=100"])
        示例输出: {"max_recall_k": 100}
    """
    updates: Dict[str, Any] = {}
    for assignment in assignments:
        if "=" not in assignment:
            msg = f"invalid assignment {assignment!r}; expected key=value"
            raise ValueError(msg)
        key, raw_value = assignment.split("=", 1)
        key = key.strip()
        if not key:
            msg = "config key must not be empty"
            raise ValueError(msg)
        updates[key] = parse_value(raw_value.strip())
    return updates


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    输入:
        无。
    输出:
        argparse.ArgumentParser: 脚本参数解析器。
    示例:
        示例输入: build_parser()
        示例输出: ArgumentParser(...)
    """
    parser = argparse.ArgumentParser(description="Update MemX hms.json")
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="Path to hms.json. Defaults to ~/.memx/hms.json.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        dest="assignments",
        help="Config update in key=value form. Can be repeated.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Run the hms.json update command.

    输入:
        argv: 可选 CLI 参数列表。
    输出:
        int: 进程退出码。
    示例:
        示例输入: main(["--set", "max_recall_k=100"])
        示例输出: 0
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        updates = parse_assignments(args.assignments)
        config = write_hms_config(updates, Path(args.config))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
