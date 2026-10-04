"""L3 semantic fact and conflict model definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .enums import ConflictAction, ConflictSeverity, ConflictType, MemoryType


@dataclass
class SemanticFact:
    """L3 semantic fact record."""

    fact_key: str
    scope_id: str
    value: Any
    confidence: float
    evidence_ids: List[str] = field(default_factory=list)
    version: int = 1
    ts_update: float = 0.0
    embedding: Optional[Tuple[float, ...]] = None
    evidence_hash: str = ""
    is_temporal: bool = False
    valid_from: Optional[float] = None
    valid_until: Optional[float] = None
    mem_type: MemoryType = MemoryType.SEMANTIC
    partition: str = "semantic"

    def __post_init__(self) -> None:
        """Validate L3 fact fields.

        输入:
            self: L3 事实对象。
        输出:
            None；非法字段会抛出 ValueError。
        示例:
            示例输入: SemanticFact("user.lang", "scope", "zh", 0.9)
            示例输出: SemanticFact 对象完成初始化，无异常。
        """
        if not self.fact_key:
            msg = "fact_key must not be empty."
            raise ValueError(msg)
        if not self.scope_id:
            msg = "scope_id must not be empty."
            raise ValueError(msg)
        if not 0 <= self.confidence <= 1:
            msg = "confidence must be in [0, 1]."
            raise ValueError(msg)
        if self.version < 1:
            msg = "version must be positive."
            raise ValueError(msg)
        if not self.partition:
            msg = "partition must not be empty."
            raise ValueError(msg)

    def content_text(self) -> str:
        """Return text used for semantic embedding and search.

        输入:
            self: L3 事实对象。
        输出:
            str: key 与 value 拼接文本。
        示例:
            示例输入: SemanticFact("k", "scope", "v", 0.9).content_text()
            示例输出: "k: v"
        """
        return f"{self.fact_key}: {self.value}"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the L3 fact.

        输入:
            self: L3 事实对象。
        输出:
            dict: 可序列化字段。
        示例:
            示例输入: fact.to_dict()
            示例输出: {"fact_key": "user.lang", "value": "zh", ...}
        """
        return {
            "fact_key": self.fact_key,
            "scope_id": self.scope_id,
            "value": self.value,
            "confidence": self.confidence,
            "evidence_ids": list(self.evidence_ids),
            "version": self.version,
            "ts_update": self.ts_update,
            "evidence_hash": self.evidence_hash,
            "is_temporal": self.is_temporal,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "mem_type": self.mem_type.value,
            "partition": self.partition,
        }


@dataclass
class ConflictRecord:
    """Audit log entry for L3 conflict detection and resolution."""

    conflict_id: str
    scope_id: str
    fact_key: Optional[str]
    conflict_type: ConflictType
    severity: ConflictSeverity
    old_value: Any
    new_value: Any
    policy_hit: str
    action: ConflictAction
    resolved_to: Any
    ts: float

    def __post_init__(self) -> None:
        """Validate conflict log fields.

        输入:
            self: 冲突日志对象。
        输出:
            None；非法字段会抛出 ValueError。
        示例:
            示例输入: ConflictRecord("c1", "scope", "k", ConflictType.VALUE, ...)
            示例输出: ConflictRecord 对象完成初始化，无异常。
        """
        if not self.conflict_id:
            msg = "conflict_id must not be empty."
            raise ValueError(msg)
        if not self.scope_id:
            msg = "scope_id must not be empty."
            raise ValueError(msg)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize a conflict log entry.

        输入:
            self: 冲突日志对象。
        输出:
            dict: conflict_log DDL 对齐字段。
        示例:
            示例输入: record.to_dict()
            示例输出: {"conflict_id": "c1", "action": "replace", ...}
        """
        return {
            "conflict_id": self.conflict_id,
            "scope_id": self.scope_id,
            "fact_key": self.fact_key,
            "conflict_type": self.conflict_type.value,
            "severity": self.severity.value,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "policy_hit": self.policy_hit,
            "action": self.action.value,
            "resolved_to": self.resolved_to,
            "ts": self.ts,
        }
