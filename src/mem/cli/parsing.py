"""CLI parsing and JSON normalization helpers."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, Sequence

from ..config import MemoryConfig
from .result import CliError


def config_to_dict(config: MemoryConfig) -> Dict[str, Any]:
    """Convert MemoryConfig into JSON-friendly values.

    输入:
        config: MemoryConfig instance。
    输出:
        dict: 可 JSON 序列化的配置。
    示例:
        示例输入: config_to_dict(MemoryConfig(max_recall_k=10))
        示例输出: {"max_recall_k": 10, ...}
    """
    return json_safe(asdict(config))


def parse_key_value_updates(pairs: Sequence[str]) -> Dict[str, Any]:
    """Parse KEY=VALUE config update arguments.

    输入:
        pairs: KEY=VALUE 字符串序列。
    输出:
        dict: key 到 JSON/scalar value 的映射。
    示例:
        示例输入: parse_key_value_updates(["max_recall_k=5"])
        示例输出: {"max_recall_k": 5}
    """
    updates: Dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise CliError(f"invalid config update: {pair}")
        key, raw_value = pair.split("=", 1)
        if not key:
            raise CliError("config update key must not be empty.")
        updates[key] = parse_scalar(raw_value)
    return updates


def parse_scalar(value: str) -> Any:
    """Parse a scalar command line value as JSON when possible.

    输入:
        value: CLI string value。
    输出:
        Any: JSON value 或原字符串。
    示例:
        示例输入: parse_scalar("10")
        示例输出: 10
    """
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def json_safe(value: Any) -> Any:
    """Convert tuples and nested containers to JSON-friendly values.

    输入:
        value: 任意 Python value。
    输出:
        Any: 可 JSON 序列化的 value。
    示例:
        示例输入: json_safe(("a", "b"))
        示例输出: ["a", "b"]
    """
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return value


def join_words(words: Sequence[str]) -> str:
    """Join argparse word tokens into user text.

    输入:
        words: argparse positional tokens。
    输出:
        str: 使用空格合并后的文本。
    示例:
        示例输入: join_words(["hello", "world"])
        示例输出: "hello world"
    """
    return " ".join(words).strip()
