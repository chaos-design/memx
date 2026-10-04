"""L1 structured working memory."""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from ..config.settings import MemoryConfig
from ..embedding.vector import token_count, tokenize
from ..memory.models import MemoryIdentity, Message, Role, WorkingMemory

# L1 slot 闭合信号：出现完成/解决类词汇时将 open slot 转为 closed。
CLOSE_PATTERN = re.compile(r"完成|done|closed|resolved|已解决|任务闭合", re.I)

# L1 slot 开启信号：出现请求、待办、约束或记忆类词汇时生成 open slot。
OPEN_PATTERN = re.compile(r"请|需要|todo|待办|实现|修复|记住|remember|must|必须", re.I)


class WorkingMemoryManager:
    """Manager for L1 summaries, slots, and mentioned entities."""

    def __init__(self, config: MemoryConfig) -> None:
        """Initialize the manager.

        输入:
            config: 系统配置。
        输出:
            None。
        示例:
            示例输入: WorkingMemoryManager(MemoryConfig())
            示例输出: WorkingMemoryManager 实例，L1 store 为空。
        """
        self.config = config
        # L1 主存储：scoped_session_key -> WorkingMemory。
        self._store: Dict[str, WorkingMemory] = {}

        # 会话身份索引：scoped_session_key -> MemoryIdentity。
        self._identities: Dict[str, MemoryIdentity] = {}

    def get_active_context(
        self,
        session_id: str,
        scope_id: str = "default",
    ) -> WorkingMemory:
        """Return or create the active L1 snapshot.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            WorkingMemory: 当前工作记忆对象。
        示例:
            示例输入: manager.get_active_context("s1", scope_id="t1")
            示例输出: WorkingMemory(session_id="s1", ...)
        """
        identity = MemoryIdentity.from_parts(session_id, scope_id)
        key = identity.scoped_session_key()
        self._identities[key] = identity
        if key not in self._store:
            self._store[key] = WorkingMemory(
                session_id=session_id,
                scope_id=scope_id,
            )
        return self._store[key]

    def compress(
        self,
        session_id: str,
        messages: List[Message],
        scope_id: str = "default",
    ) -> WorkingMemory:
        """Compress raw L0 messages into L1.

        输入:
            session_id: 会话 ID。
            messages: L0 消息窗口。
            scope_id: 作用域 ID。
        输出:
            WorkingMemory: 更新后的 L1。
        示例:
            示例输入: manager.compress("s1", messages, scope_id="t1")
            示例输出: token_used 已更新的 WorkingMemory 对象。
        """
        if messages:
            first = messages[0]
            scope_id = first.scope_id
        memory = self.get_active_context(session_id, scope_id)
        if not messages:
            return memory
        summary_piece = self._summarize(messages)
        memory.rolling_summary = self._fit_summary(
            " ".join(part for part in [memory.rolling_summary, summary_piece] if part)
        )
        memory.mentioned_entities = self._merge_entities(
            memory.mentioned_entities, self._extract_entities(messages)
        )
        memory.open_slots.extend(self._extract_slots(messages))
        memory.token_used = token_count(memory.to_context())
        memory.last_compress_ts = max(message.ts for message in messages)
        if memory.token_used > self.config.working_memory_tokens:
            memory.rolling_summary = self._fit_summary(memory.rolling_summary)
            memory.token_used = token_count(memory.to_context())
        return memory

    def promote(
        self,
        session_id: str,
        scope_id: str = "default",
    ) -> List[Dict[str, Any]]:
        """Return closed slots and remove them from L1.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            list[dict]: 可下沉 L2 的闭合 slot。
        示例:
            示例输入: manager.promote("s1", scope_id="t1")
            示例输出: [{"slot_id": "s1:2", "status": "closed", ...}]
        """
        memory = self.get_active_context(session_id, scope_id)
        closed_slots = [
            slot for slot in memory.open_slots if slot.get("status") == "closed"
        ]
        memory.open_slots = [
            slot for slot in memory.open_slots if slot.get("status") != "closed"
        ]
        memory.token_used = token_count(memory.to_context())
        return closed_slots

    def close_matching_slots(
        self,
        session_id: str,
        marker: str = "",
        scope_id: str = "default",
    ) -> List[Dict[str, Any]]:
        """Mark open slots as closed when a completion signal appears.

        输入:
            session_id: 会话 ID。
            marker: 可选闭合说明。
            scope_id: 作用域 ID。
        输出:
            list[dict]: 被闭合的 slot。
        示例:
            示例输入: manager.close_matching_slots("s1", "done", scope_id="t1")
            示例输出: [{"status": "closed", "closed_reason": "done", ...}]
        """
        memory = self.get_active_context(session_id, scope_id)
        closed = []
        for slot in memory.open_slots:
            if slot.get("status") == "open":
                slot["status"] = "closed"
                slot["closed_reason"] = marker or "completion signal"
                slot["closed_ts"] = time.time()
                closed.append(slot)
        return closed

    def active_sessions(self, scope_id: Optional[str] = None) -> List[MemoryIdentity]:
        """Return identities that currently have L1 state.

        输入:
            scope_id: 可选作用域过滤。
        输出:
            list[MemoryIdentity]: 活跃 L1 会话身份列表。
        示例:
            示例输入: manager.active_sessions("t1")
            示例输出: [MemoryIdentity(scope_id="t1", session_id="s1")]
        """
        identities = []
        for key, memory in self._store.items():
            identity = self._identities.get(
                key,
                MemoryIdentity(memory.scope_id, memory.session_id),
            )
            if scope_id is None or identity.scope_id == scope_id:
                identities.append(identity)
        return identities

    def _summarize(self, messages: List[Message]) -> str:
        """Create a deterministic rolling summary segment.

        输入:
            messages: L0 消息列表。
        输出:
            str: 摘要片段。
        示例:
            示例输入: manager._summarize(messages)
            示例输出: "user: 请实现 Agent 记忆系统 | assistant: 处理中"
        """
        snippets = []
        for message in messages:
            text = message.content.strip().replace("\n", " ")
            if len(text) > 160:
                text = text[:157] + "..."
            snippets.append(f"{message.role.value}: {text}")
        return " | ".join(snippets)

    def _fit_summary(self, summary: str) -> str:
        """Trim rolling summary to fit the L1 capacity budget.

        输入:
            summary: 原摘要。
        输出:
            str: 截断后的摘要。
        示例:
            示例输入: manager._fit_summary("long text")
            示例输出: "long text"
        """
        if token_count(summary) <= self.config.working_memory_tokens:
            return summary
        tokens = tokenize(summary)
        if not tokens:
            return summary[-self.config.working_memory_tokens :]
        kept = tokens[-self.config.working_memory_tokens :]
        return " ".join(kept)

    def _extract_slots(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Extract structured slots from raw messages.

        输入:
            messages: L0 消息列表。
        输出:
            list[dict]: 任务或约束 slot。
        示例:
            示例输入: manager._extract_slots(messages)
            示例输出: [{"slot_id": "s1:1", "text": "...", "status": "open", ...}]
        """
        slots = []
        for message in messages:
            if message.role != Role.USER:
                continue
            is_open = OPEN_PATTERN.search(message.content) is not None
            is_closed = CLOSE_PATTERN.search(message.content) is not None
            if not is_open and not is_closed:
                continue
            slots.append(
                {
                    "slot_id": f"{message.session_id}:{message.turn_id}",
                    "text": message.content,
                    "status": "closed" if is_closed else "open",
                    "source_ids": [message.source_id()],
                    "ts": message.ts,
                    "scope_id": message.scope_id,
                    "session_id": message.session_id,
                    "user_emphasis": "记住" in message.content
                    or "remember" in message.content.lower(),
                }
            )
        return slots

    def _extract_entities(self, messages: List[Message]) -> List[str]:
        """Extract lightweight mentioned entities.

        输入:
            messages: L0 消息列表。
        输出:
            list[str]: 去重后的实体候选。
        示例:
            示例输入: manager._extract_entities(messages)
            示例输出: ["Agent", "agent", "记忆系统"]
        """
        entities = []
        for message in messages:
            for word in re.findall(r"[A-Za-z][A-Za-z0-9_]+", message.content):
                if word not in entities:
                    entities.append(word)
            for token in tokenize(message.content):
                if len(token) >= 2 and token not in entities:
                    entities.append(token)
            for char in re.findall(r"[\u4e00-\u9fff]{2,}", message.content):
                if char not in entities:
                    entities.append(char)
        return entities[:32]

    def _merge_entities(self, left: List[str], right: List[str]) -> List[str]:
        """Merge entity lists while preserving order.

        输入:
            left: 现有实体列表。
            right: 新实体列表。
        输出:
            list[str]: 合并后最多 64 项。
        示例:
            示例输入: manager._merge_entities(["A"], ["A", "B"])
            示例输出: ["A", "B"]
        """
        merged = list(left)
        for entity in right:
            if entity not in merged:
                merged.append(entity)
        return merged[:64]
