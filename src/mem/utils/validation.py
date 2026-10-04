"""Reusable validation helpers."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any, Dict, Type

from ..exceptions import ValidationError


def validate_recall_k(k: int, max_recall_k: int) -> None:
    """Validate a recall size against configured bounds.

    输入:
        k: 请求返回数量。
        max_recall_k: 配置允许的最大返回数量。
    输出:
        None；非法时抛出 ValidationError。
    示例:
        示例输入: validate_recall_k(8, 50)
        示例输出: None
    """
    if not 0 < k <= max_recall_k:
        msg = "k must be in [1, max_recall_k]."
        raise ValidationError(msg)


def validate_importance(importance: int) -> None:
    """Validate a memory importance score.

    输入:
        importance: 重要性分数。
    输出:
        None；非法时抛出 ValidationError。
    示例:
        示例输入: validate_importance(8)
        示例输出: None
    """
    if not 0 <= importance <= 10:
        msg = "importance must be in [0, 10]."
        raise ValidationError(msg)


def dataclass_field_names(dataclass_type: Type[object]) -> set:
    """Return field names for a dataclass type.

    输入:
        dataclass_type: dataclass 类型。
    输出:
        set: 字段名集合。
    示例:
        示例输入: dataclass_field_names(MemoryConfig)
        示例输出: {"backend_mode", ...}
    """
    if not is_dataclass(dataclass_type):
        msg = "dataclass_type must be a dataclass."
        raise ValidationError(msg)
    return {field.name for field in fields(dataclass_type)}


def validate_config_updates(
    updates: Dict[str, Any], dataclass_type: Type[object]
) -> None:
    """Validate that config update keys belong to a dataclass.

    输入:
        updates: 配置更新字典。
        dataclass_type: 配置 dataclass 类型。
    输出:
        None；未知字段会抛出 ValidationError。
    示例:
        示例输入: validate_config_updates({"max_recall_k": 10}, MemoryConfig)
        示例输出: None
    """
    allowed = dataclass_field_names(dataclass_type)
    unknown = sorted(set(updates) - allowed)
    if unknown:
        msg = f"unknown config keys: {', '.join(unknown)}"
        raise ValidationError(msg)
