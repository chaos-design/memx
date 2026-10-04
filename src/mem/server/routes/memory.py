"""Memory operation routes for the MemX server."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from ..dependencies import memory_from_request
from ..schemas import (
    ForgetRequest,
    MemorizeRequest,
    ObserveRequest,
    RecallRequest,
    ReflectRequest,
    SearchRequest,
    UpdateRequest,
)
from .paths import (
    MEMORY_FORGET_PATH,
    MEMORY_MEMORIZE_PATH,
    MEMORY_OBSERVE_PATH,
    MEMORY_RECALL_PATH,
    MEMORY_REFLECT_PATH,
    MEMORY_SEARCH_PATH,
    MEMORY_UPDATE_PATH,
)

router = APIRouter(tags=["memory"])


@router.post(MEMORY_OBSERVE_PATH)
def observe(request: Request, payload: ObserveRequest) -> Dict[str, Any]:
    """Observe one message.

    输入:
        request: FastAPI request object.
        payload: observe request body.
    输出:
        dict: observe result.
    示例:
        示例输入: POST /memory/observe
        示例输出: {"promoted": [...], ...}
    """
    return memory_from_request(request).observe(
        payload.session_id,
        payload.msg,
    )


@router.post(MEMORY_MEMORIZE_PATH)
def memorize(request: Request, payload: MemorizeRequest) -> Dict[str, Any]:
    """Write explicit memory text.

    输入:
        request: FastAPI request object.
        payload: memorize request body.
    输出:
        dict: memorize result.
    示例:
        示例输入: POST /memory/memorize
        示例输出: {"mem_id": "...", "importance": 8}
    """
    return memory_from_request(request).memorize(
        payload.session_id,
        payload.text,
        importance=payload.importance,
    )


@router.post(MEMORY_RECALL_PATH)
def recall(request: Request, payload: RecallRequest) -> Dict[str, Any]:
    """Recall memory context.

    输入:
        request: FastAPI request object.
        payload: recall request body.
    输出:
        dict: recall result.
    示例:
        示例输入: POST /memory/recall
        示例输出: {"facts": [...], "episodes": [...]}
    """
    return memory_from_request(request).recall(
        session_id=payload.session_id,
        query=payload.query,
        k=payload.k,
        entities=payload.entities,
        include_archived=payload.include_archived,
    )


@router.post(MEMORY_SEARCH_PATH)
def search(request: Request, payload: SearchRequest) -> Dict[str, Any]:
    """Search active memory context.

    输入:
        request: FastAPI request object.
        payload: search request body.
    输出:
        dict: search result.
    示例:
        示例输入: POST /memory/search
        示例输出: {"facts": [...], "episodes": [...]}
    """
    return memory_from_request(request).search(
        payload.session_id,
        payload.query,
        k=payload.k,
    )


@router.patch(MEMORY_UPDATE_PATH)
def update_memory(request: Request, payload: UpdateRequest) -> Dict[str, Any]:
    """Update memory content or facts.

    输入:
        request: FastAPI request object.
        payload: update request body.
    输出:
        dict: update result.
    示例:
        示例输入: PATCH /memory/update
        示例输出: {"action": "updated", ...}
    """
    if not payload.payload:
        raise HTTPException(status_code=400, detail="payload must not be empty")
    return memory_from_request(request).update(payload.payload)


@router.post(MEMORY_FORGET_PATH)
def forget(request: Request, payload: ForgetRequest) -> Dict[str, Any]:
    """Forget memory content.

    输入:
        request: FastAPI request object.
        payload: forget request body.
    输出:
        dict: forget result.
    示例:
        示例输入: POST /memory/forget
        示例输出: {"deleted": 1}
    """
    return memory_from_request(request).forget(
        mode=payload.mode,
        mem_id=payload.mem_id,
        force=payload.force,
    )


@router.post(MEMORY_REFLECT_PATH)
def reflect(request: Request, payload: ReflectRequest) -> Dict[str, Any]:
    """Run memory reflection.

    输入:
        request: FastAPI request object.
        payload: reflect request body.
    输出:
        dict: reflect result.
    示例:
        示例输入: POST /memory/reflect
        示例输出: {"n_facts": 1, ...}
    """
    return memory_from_request(request).reflect(force=payload.force)
