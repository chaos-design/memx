"""Timestamp helpers."""

from __future__ import annotations

import time as time_module
from typing import Optional


def current_timestamp() -> float:
    """Return the current Unix timestamp.

    输入:
        无。
    输出:
        float: 当前 Unix 时间戳。
    示例:
        示例输入: current_timestamp()
        示例输出: 1719000000.0
    """
    return time_module.time()


def coalesce_timestamp(value: Optional[float]) -> float:
    """Return a provided timestamp or the current timestamp.

    输入:
        value: 可选时间戳。
    输出:
        float: 传入值或当前时间戳。
    示例:
        示例输入: coalesce_timestamp(1.0)
        示例输出: 1.0
    """
    if value is None:
        return current_timestamp()
    return float(value)
