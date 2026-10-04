"""Reusable validation helpers."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any, Dict, Type, Union, get_args, get_origin, get_type_hints

from ..exceptions import ConfigurationError, ValidationError

_SEQUENCE_ORIGINS = (list, tuple, set, frozenset)


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


def _annotation_accepts(value: Any, annotation: Any) -> bool:
    """Return whether a value satisfies a dataclass field annotation.

    输入:
        value: 待校验的配置值。
        annotation: 字段的类型注解。
    输出:
        bool: 类型兼容时为 True；注解无法判定时按兼容处理。
    示例:
        示例输入: _annotation_accepts("abc", int)
        示例输出: False
    """
    origin = get_origin(annotation)
    if origin is Union:
        return any(_annotation_accepts(value, arg) for arg in get_args(annotation))
    if origin in _SEQUENCE_ORIGINS:
        # JSON 没有 tuple 类型，序列注解必须同时接受 list。
        if not isinstance(value, (list, tuple, set, frozenset)):
            return False
        args = get_args(annotation)
        if not args or args == (Ellipsis,):
            return True
        if len(args) == 2 and args[1] is Ellipsis:
            return all(_annotation_accepts(item, args[0]) for item in value)
        return all(_annotation_accepts(item, arg) for item, arg in zip(value, args))
    if annotation is bool:
        return isinstance(value, bool)
    if annotation is int:
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        # JSON 字面量可能写成 8.0，接受可无损窄化为整数的浮点。
        return isinstance(value, float) and value.is_integer()
    if annotation is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if annotation in _SEQUENCE_ORIGINS:
        return isinstance(value, (list, tuple, set, frozenset))
    if isinstance(annotation, type):
        return isinstance(value, annotation)
    return True


def _annotation_name(annotation: Any) -> str:
    """Return a readable name for a type annotation.

    输入:
        annotation: 类型注解。
    输出:
        str: 可读的类型名。
    示例:
        示例输入: _annotation_name(int)
        示例输出: "int"
    """
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def validate_config_updates(
    updates: Dict[str, Any], dataclass_type: Type[object]
) -> None:
    """Validate that config update keys and value types fit a dataclass.

    校验顺序固定为先 key 后类型：未知字段抛 ValidationError，
    类型不匹配抛 ConfigurationError 并在消息中点名具体字段，
    避免错误一路冒泡到构造器内部变成无法定位的 TypeError。

    输入:
        updates: 配置更新字典。
        dataclass_type: 配置 dataclass 类型。
    输出:
        None；非法配置会抛出 ValidationError 或 ConfigurationError。
    示例:
        示例输入: validate_config_updates({"max_recall_k": 10}, MemoryConfig)
        示例输出: None
    """
    allowed = dataclass_field_names(dataclass_type)
    unknown = sorted(set(updates) - allowed)
    if unknown:
        msg = f"unknown config keys: {', '.join(unknown)}"
        raise ValidationError(msg)
    hints = get_type_hints(dataclass_type)
    mismatched = [
        f"{key}={updates[key]!r} (expected {_annotation_name(hints[key])})"
        for key in sorted(updates)
        if key in hints and not _annotation_accepts(updates[key], hints[key])
    ]
    if mismatched:
        msg = f"invalid config value types: {', '.join(mismatched)}"
        raise ConfigurationError(msg)
