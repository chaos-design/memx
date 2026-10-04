"""Hashing helpers for stable memory identifiers."""

from __future__ import annotations

import hashlib


def short_hash(text: str, digest_size: int = 4) -> str:
    """Create a stable short hash for labels and fact keys.

    输入:
        text: 原始文本。
        digest_size: BLAKE2b digest 字节数。
    输出:
        str: 十六进制短 hash。
    示例:
        示例输入: short_hash("abc")
        示例输出: "cf4ab791"
    """
    return hashlib.blake2b(text.encode("utf-8"), digest_size=digest_size).hexdigest()


def memory_fingerprint(scope_id: str, text: str) -> str:
    """Create a deterministic memory id from scope and normalized text.

    输入:
        scope_id: 作用域 ID。
        text: 记忆正文。
    输出:
        str: `m_` 前缀的稳定记忆 ID。
    示例:
        示例输入: memory_fingerprint("scope", "remember x")
        示例输出: "m_..."。
    """
    normalized = " ".join(text.split())
    payload = f"{scope_id}\0{normalized}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=16).hexdigest()
    return f"m_{digest}"
