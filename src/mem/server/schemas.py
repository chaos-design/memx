"""Pydantic schemas for the MemX FastAPI server."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ObserveRequest(BaseModel):
    """Request body for observing one message."""

    session_id: str
    msg: Dict[str, Any]


class MemorizeRequest(BaseModel):
    """Request body for explicit memory writes."""

    session_id: str
    text: str
    importance: Optional[int] = None


class RecallRequest(BaseModel):
    """Request body for recall."""

    session_id: str
    query: str
    k: int = 8
    entities: Optional[List[str]] = None
    include_archived: bool = True


class SearchRequest(BaseModel):
    """Request body for active memory search."""

    session_id: str
    query: str
    k: int = 8


class UpdateRequest(BaseModel):
    """Request body for updating memories or facts."""

    payload: Dict[str, Any] = Field(default_factory=dict)


class ForgetRequest(BaseModel):
    """Request body for forget operations."""

    mode: str = "decay"
    mem_id: Optional[str] = None
    force: bool = False


class ReflectRequest(BaseModel):
    """Request body for reflection."""

    force: bool = False


class MaintenanceRequest(BaseModel):
    """Request body for one-shot maintenance."""

    tasks: Optional[List[str]] = None
    force_reflect: bool = False


class ConfigPatchRequest(BaseModel):
    """Request body for hms.json updates."""

    updates: Dict[str, Any] = Field(default_factory=dict)
