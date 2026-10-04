"""Consolidation inbox abstractions for asynchronous memory evolution."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from typing import DefaultDict, Dict, List, Optional

from ..memory.models import (
    ConsolidationInboxItem,
    EpisodicMemory,
    InboxStatus,
    MemoryType,
)


class InMemoryInbox:
    """Scope-partitioned inbox for pending consolidation candidates."""

    def __init__(self, max_retries: int = 3) -> None:
        """Initialize the inbox.

        输入:
            max_retries: 单条固化任务最大重试次数。
        输出:
            None。
        示例:
            示例输入: InMemoryInbox(max_retries=2)
            示例输出: InMemoryInbox 实例，内部队列为空。
        """
        if max_retries <= 0:
            msg = "max_retries must be positive."
            raise ValueError(msg)
        self.max_retries = max_retries
        self._items: DefaultDict[str, Dict[str, ConsolidationInboxItem]] = (
            defaultdict(dict)
        )

    def enqueue(
        self,
        memory: EpisodicMemory,
        mem_type_hint: Optional[MemoryType] = None,
        now_ts: Optional[float] = None,
    ) -> ConsolidationInboxItem:
        """Enqueue or refresh a memory consolidation candidate.

        输入:
            memory: L2 情景记忆对象。
            mem_type_hint: 可选逻辑类型提示。
            now_ts: 入队时间戳；None 使用当前时间。
        输出:
            ConsolidationInboxItem: 入队或刷新后的条目。
        示例:
            示例输入: inbox.enqueue(memory)
            示例输出: ConsolidationInboxItem(status=InboxStatus.PENDING, ...)
        """
        if now_ts is None:
            now_ts = time.time()
        item_id = self._item_id(memory.scope_id, memory.mem_id)
        scope_items = self._items[memory.scope_id]
        existing = scope_items.get(item_id)
        if existing is not None:
            if existing.status in {InboxStatus.FAILED, InboxStatus.DONE}:
                existing.status = InboxStatus.PENDING
                existing.retry_count = 0
                existing.last_error = None
            existing.priority = max(existing.priority, float(memory.importance))
            existing.mem_type_hint = mem_type_hint or memory.mem_type
            return existing
        item = ConsolidationInboxItem(
            item_id=item_id,
            scope_id=memory.scope_id,
            mem_id=memory.mem_id,
            text=memory.text,
            priority=float(memory.importance),
            ts_enqueue=now_ts,
            mem_type_hint=mem_type_hint or memory.mem_type,
        )
        scope_items[item_id] = item
        return item

    def pull(self, scope_id: str, limit: int = 50) -> List[ConsolidationInboxItem]:
        """Pull a bounded batch of pending items.

        输入:
            scope_id: 作用域 ID。
            limit: 最大拉取数量。
        输出:
            list[ConsolidationInboxItem]: 状态已置为 processing 的条目。
        示例:
            示例输入: inbox.pull("scope", limit=10)
            示例输出: [ConsolidationInboxItem(...)]
        """
        if limit <= 0:
            return []
        pending = [
            item
            for item in self._items.get(scope_id, {}).values()
            if item.status == InboxStatus.PENDING
        ]
        pending = sorted(
            pending,
            key=lambda item: (-item.priority, item.ts_enqueue, item.item_id),
        )[:limit]
        for item in pending:
            item.status = InboxStatus.PROCESSING
        return pending

    def mark_done(self, scope_id: str, item_id: str) -> None:
        """Mark one inbox item as done.

        输入:
            scope_id: 作用域 ID。
            item_id: inbox 条目 ID。
        输出:
            None。
        示例:
            示例输入: inbox.mark_done("scope", "ci_x")
            示例输出: None，条目状态更新为 done。
        """
        item = self._items.get(scope_id, {}).get(item_id)
        if item is not None:
            item.status = InboxStatus.DONE
            item.last_error = None

    def mark_failed(self, scope_id: str, item_id: str, error: str) -> None:
        """Mark one inbox item as failed or retryable.

        输入:
            scope_id: 作用域 ID。
            item_id: inbox 条目 ID。
            error: 失败原因。
        输出:
            None。
        示例:
            示例输入: inbox.mark_failed("scope", "ci_x", "bad json")
            示例输出: None，条目进入 pending 或 failed。
        """
        item = self._items.get(scope_id, {}).get(item_id)
        if item is None:
            return
        item.retry_count += 1
        item.last_error = error
        if item.retry_count >= self.max_retries:
            item.status = InboxStatus.FAILED
        else:
            item.status = InboxStatus.PENDING

    def pending_count(self, scope_id: str) -> int:
        """Return the pending item count for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            int: pending 状态条目数。
        示例:
            示例输入: inbox.pending_count("scope")
            示例输出: 3
        """
        return self._count_by_status(scope_id, InboxStatus.PENDING)

    def stats(self, scope_id: str) -> Dict[str, int]:
        """Return status counts for a scope inbox.

        输入:
            scope_id: 作用域 ID。
        输出:
            dict: pending、processing、done、failed 计数。
        示例:
            示例输入: inbox.stats("scope")
            示例输出: {"pending": 1, "processing": 0, "done": 2, "failed": 0}
        """
        return {
            status.value: self._count_by_status(scope_id, status)
            for status in InboxStatus
        }

    def snapshot(self, scope_id: str) -> List[Dict[str, object]]:
        """Return a serializable inbox snapshot.

        输入:
            scope_id: 作用域 ID。
        输出:
            list[dict]: inbox 条目快照。
        示例:
            示例输入: inbox.snapshot("scope")
            示例输出: [{"item_id": "ci_x", "status": "pending", ...}]
        """
        return [
            item.to_dict()
            for item in sorted(
                self._items.get(scope_id, {}).values(),
                key=lambda item: (item.ts_enqueue, item.item_id),
            )
        ]

    def _count_by_status(self, scope_id: str, status: InboxStatus) -> int:
        """Count scope inbox items by status.

        输入:
            scope_id: 作用域 ID。
            status: 目标状态。
        输出:
            int: 命中条目数量。
        示例:
            示例输入: inbox._count_by_status("scope", InboxStatus.PENDING)
            示例输出: 1
        """
        return sum(
            1
            for item in self._items.get(scope_id, {}).values()
            if item.status == status
        )

    def _item_id(self, scope_id: str, mem_id: str) -> str:
        """Create a stable inbox item ID.

        输入:
            scope_id: 作用域 ID。
            mem_id: L2 记忆 ID。
        输出:
            str: ci_ 前缀的稳定条目 ID。
        示例:
            示例输入: inbox._item_id("scope", "m1")
            示例输出: "ci_..."。
        """
        payload = f"{scope_id}\0{mem_id}".encode("utf-8")
        digest = hashlib.blake2b(payload, digest_size=12).hexdigest()
        return f"ci_{digest}"
