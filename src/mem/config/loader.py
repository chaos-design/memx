"""Load and update MemX configuration from hms.json."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from ..constants import HMS_CONFIG_FILENAME
from ..exceptions import ConfigurationError
from ..utils.json import merge_json_objects, read_json_object, write_json_object
from ..utils.validation import validate_config_updates
from .settings import MemoryConfig

ConfigPath = Union[str, Path]


def default_config_path() -> Path:
    """Return the user-level default hms.json path.

    输入:
        无。
    输出:
        Path: `~/.memx/hms.json` 的路径。
    示例:
        示例输入: default_config_path()
        示例输出: Path("~/.memx/hms.json")
    """
    return Path.home() / ".memx" / HMS_CONFIG_FILENAME


def read_hms_config(path: Optional[ConfigPath] = None) -> Dict[str, Any]:
    """Read raw hms.json configuration.

    输入:
        path: 可选配置文件路径；None 使用 `~/.memx/hms.json`。
    输出:
        dict: 配置键值；文件不存在时为空字典。
    示例:
        示例输入: read_hms_config()
        示例输出: {"max_recall_k": 50, ...}
    """
    config_path = Path(path) if path is not None else default_config_path()
    try:
        config = read_json_object(config_path)
    except ValueError as exc:
        msg = f"invalid hms config file: {config_path}"
        raise ConfigurationError(msg) from exc
    validate_config_updates(config, MemoryConfig)
    return config


def load_memory_config(
    path: Optional[ConfigPath] = None,
    overrides: Optional[Mapping[str, Any]] = None,
) -> MemoryConfig:
    """Load MemoryConfig from defaults, hms.json, and explicit overrides.

    输入:
        path: 可选 hms.json 路径。
        overrides: 显式覆盖配置。
    输出:
        MemoryConfig: 已校验的配置对象。
    示例:
        示例输入: load_memory_config(overrides={"max_recall_k": 10})
        示例输出: MemoryConfig(max_recall_k=10, ...)
    """
    file_config = read_hms_config(path)
    override_config = dict(overrides or {})
    validate_config_updates(override_config, MemoryConfig)
    merged = merge_json_objects(file_config, override_config)
    coerced = _coerce_config_values(merged)
    try:
        return MemoryConfig(**coerced)
    except (TypeError, ValueError) as exc:
        # 配置值类型混淆（例如 hms.json 里把 flush_turns 写成字符串）会在边界校验阶段
        # 抛出 TypeError 而非 ValueError，这里统一收敛为 ConfigurationError，
        # 并保留原始信息以便定位具体是哪个字段非法。
        msg = f"invalid MemX configuration: {exc}"
        raise ConfigurationError(msg) from exc


def write_hms_config(
    updates: Mapping[str, Any],
    path: Optional[ConfigPath] = None,
) -> Dict[str, Any]:
    """Update hms.json with validated config values.

    输入:
        updates: 配置更新键值。
        path: 可选 hms.json 路径。
    输出:
        dict: 写入后的完整配置。
    示例:
        示例输入: write_hms_config({"max_recall_k": 10})
        示例输出: {"max_recall_k": 10, ...}
    """
    config_path = Path(path) if path is not None else default_config_path()
    update_dict = dict(updates)
    validate_config_updates(update_dict, MemoryConfig)
    current = read_hms_config(config_path)
    merged = merge_json_objects(current, update_dict)
    validated = load_memory_config(config_path, update_dict)
    serializable = _to_json_config(merged, validated)
    write_json_object(config_path, serializable)
    return serializable


def _coerce_config_values(config: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce JSON values into MemoryConfig-compatible values.

    输入:
        config: JSON 字典。
    输出:
        dict: 可传入 MemoryConfig 的字典。
    示例:
        示例输入: _coerce_config_values({"temporal_fact_keys": ["a"]})
        示例输出: {"temporal_fact_keys": ("a",)}
    """
    coerced = dict(config)
    if "temporal_fact_keys" in coerced and isinstance(
        coerced["temporal_fact_keys"], list
    ):
        coerced["temporal_fact_keys"] = tuple(coerced["temporal_fact_keys"])
    return coerced


def _to_json_config(
    config: Mapping[str, Any],
    validated: MemoryConfig,
) -> Dict[str, Any]:
    """Normalize config values for JSON persistence.

    输入:
        config: 用户配置字典。
        validated: 已校验配置对象。
    输出:
        dict: 可 JSON 序列化的配置字典。
    示例:
        示例输入: _to_json_config({"temporal_fact_keys": ("a",)}, config)
        示例输出: {"temporal_fact_keys": ["a"]}
    """
    normalized = dict(config)
    valid_fields = {field.name for field in fields(MemoryConfig)}
    for key in list(normalized):
        if key not in valid_fields:
            del normalized[key]
    if "temporal_fact_keys" in normalized:
        normalized["temporal_fact_keys"] = list(validated.temporal_fact_keys)
    return normalized
