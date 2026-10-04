"""JSON file helpers with deterministic formatting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def read_json_object(path: Path) -> Dict[str, Any]:
    """Read a JSON object from disk.

    输入:
        path: JSON 文件路径。
    输出:
        dict: JSON object；文件不存在时返回空字典。
    示例:
        示例输入: read_json_object(Path("missing.json"))
        示例输出: {}
    """
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = "JSON config must be an object."
        raise ValueError(msg)
    return data


def write_json_object(path: Path, data: Dict[str, Any]) -> Path:
    """Write a JSON object with deterministic formatting.

    输入:
        path: JSON 文件路径。
        data: 待写入对象。
    输出:
        Path: 写入后的文件路径。
    示例:
        示例输入: write_json_object(Path("config.json"), {"a": 1})
        示例输出: Path("config.json")
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def merge_json_objects(
    base: Optional[Dict[str, Any]] = None,
    *overlays: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge JSON-like dictionaries from left to right.

    输入:
        base: 基础字典。
        overlays: 后续覆盖字典。
    输出:
        dict: 合并后的新字典。
    示例:
        示例输入: merge_json_objects({"a": 1}, {"a": 2})
        示例输出: {"a": 2}
    """
    result: Dict[str, Any] = dict(base or {})
    for overlay in overlays:
        if overlay:
            result.update(overlay)
    return result
