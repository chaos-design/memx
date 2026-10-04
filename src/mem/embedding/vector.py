"""Deterministic local embedding utilities.

The implementation is intentionally dependency-free. It provides stable vectors
for tests and local development while keeping the embedding boundary replaceable.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, List, Sequence, Tuple

# 本地 tokenizer 的正则：英文/数字/下划线按词切分，中文按单字切分。
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> List[str]:
    """Tokenize English words and Chinese characters.

    输入:
        text: 原始文本。
    输出:
        list[str]: 归一化 token 列表。
    示例:
        示例输入: tokenize("Agent 记忆")
        示例输出: ["agent", "记", "忆"]
    """
    return TOKEN_PATTERN.findall(text.lower())


def token_count(text: str) -> int:
    """Estimate token length for capacity checks.

    输入:
        text: 原始文本。
    输出:
        int: token 数量估计值，空白文本返回 0。
    示例:
        示例输入: token_count("hello world")
        示例输出: 2
    """
    tokens = tokenize(text)
    if tokens:
        return len(tokens)
    return len(text.split())


def _hash_index(token: str, dimensions: int) -> int:
    """Map a token to a deterministic vector index.

    输入:
        token: 已归一化 token。
        dimensions: 向量维度。
    输出:
        int: 目标维度下标。
    示例:
        示例输入: _hash_index("agent", 64)
        示例输出: 0 到 63 之间的稳定整数。
    """
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dimensions


def _normalize(values: Iterable[float]) -> Tuple[float, ...]:
    """L2-normalize a sequence of numbers.

    输入:
        values: 原始向量值。
    输出:
        tuple[float, ...]: 单位向量；零向量保持为零。
    示例:
        示例输入: _normalize([3.0, 4.0])
        示例输出: (0.6, 0.8)
    """
    vector = tuple(values)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return tuple(value / norm for value in vector)


def embed_text(text: str, dimensions: int = 64) -> Tuple[float, ...]:
    """Create a deterministic bag-of-tokens embedding.

    输入:
        text: 待编码文本。
        dimensions: 向量维度。
    输出:
        tuple[float, ...]: 归一化向量。
    示例:
        示例输入: embed_text("Agent memory", 16)
        示例输出: 长度为 16 的归一化 tuple。
    """
    if dimensions <= 0:
        msg = "dimensions must be positive."
        raise ValueError(msg)
    vector = [0.0] * dimensions
    for token in tokenize(text):
        vector[_hash_index(token, dimensions)] += 1.0
    return _normalize(vector)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Compute cosine similarity for normalized or raw vectors.

    输入:
        left: 左向量。
        right: 右向量。
    输出:
        float: 余弦相似度；维度不匹配会抛出 ValueError。
    示例:
        示例输入: cosine_similarity((1.0, 0.0), (1.0, 0.0))
        示例输出: 1.0
    """
    if len(left) != len(right):
        msg = "vectors must have the same dimensions."
        raise ValueError(msg)
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot = sum(l_value * r_value for l_value, r_value in zip(left, right))
    return dot / (left_norm * right_norm)
