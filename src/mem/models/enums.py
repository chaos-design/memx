"""Shared enum values for MemX models."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """Message role values accepted by L0."""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class MemoryStatus(str, Enum):
    """Lifecycle status for L2 episodic memories."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class MemoryType(str, Enum):
    """Logical memory type values used for routing and partitioning."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PREFERENCE = "preference"
    PROCEDURAL = "procedural"


class InboxStatus(str, Enum):
    """Status values for consolidation inbox items."""

    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class NodeType(str, Enum):
    """Node type values for the L4 cognitive graph."""

    ENTITY = "entity"
    CONCEPT = "concept"
    INSIGHT = "insight"


class EdgeType(str, Enum):
    """Edge type values for the L4 cognitive graph."""

    CAUSE = "cause"
    BELONG = "belong"
    TEMPORAL = "temporal"
    SIMILAR = "similar"


class InsightStatus(str, Enum):
    """Status values for insight nodes."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"


class ConflictType(str, Enum):
    """Conflict categories used by the L3 governance gate."""

    VALUE = "value"
    TEMPORAL = "temporal"
    NEGATION = "negation"
    SOURCE = "source"
    GRAPH = "graph"


class ConflictSeverity(str, Enum):
    """Conflict severity levels."""

    HIGH = "high"
    MID = "mid"
    LOW = "low"


class ConflictAction(str, Enum):
    """Conflict resolution actions."""

    REPLACE = "replace"
    MERGE = "merge"
    ARCHIVE = "archive"
    PENDING = "pending"
    REJECT = "reject"
    KEEP = "keep"
