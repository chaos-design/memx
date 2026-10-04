"""L0 sensory conversation buffer."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import DefaultDict, Dict, List, Optional

from ..config.settings import MemoryConfig
from ..embedding.vector import token_count
from ..memory.models import MemoryIdentity, Message, Role


class ConversationBuffer:
    """In-memory ring buffer for raw conversation messages."""

    def __init__(self, config: MemoryConfig) -> None:
        """Initialize the buffer.

        输入:
            config: 系统配置。
        输出:
            None。
        示例:
            示例输入: ConversationBuffer(MemoryConfig())
            示例输出: ConversationBuffer 实例，内部消息窗口为空。
        """
        self.config = config

        # L0 当前窗口：scoped_session_key -> 最近原始 Message 列表。
        self._messages: DefaultDict[str, List[Message]] = defaultdict(list)

        # L0 总轮次计数：scoped_session_key -> 已写入 turn 数。
        self._turns: DefaultDict[str, int] = defaultdict(int)

        # 被 TTL 或环形容量淘汰、等待补偿压缩到 L1 的消息列表。
        self._evicted: DefaultDict[str, List[Message]] = defaultdict(list)

        # 会话身份索引：scoped_session_key -> MemoryIdentity。
        self._identities: Dict[str, MemoryIdentity] = {}

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        ts: Optional[float] = None,
        scope_id: str = "default",
    ) -> Message:
        """Append a raw message to L0.

        输入:
            session_id: 会话 ID。
            role: user/assistant/tool/system。
            content: 消息正文。
            ts: 可选时间戳。
            scope_id: 作用域 ID。
        输出:
            Message: 写入后的消息对象。
        示例:
            示例输入: buffer.append("s1", "user", "hello", ts=1.0, scope_id="t1")
            示例输出: Message(turn_id=1, role=Role.USER, content="hello", ...)
        """
        if ts is None:
            ts = time.time()
        identity = MemoryIdentity.from_parts(session_id, scope_id)
        key = identity.scoped_session_key()
        self._identities[key] = identity
        self._turns[key] += 1
        message = Message(
            turn_id=self._turns[key],
            role=Role(role),
            content=content,
            ts=ts,
            token_len=token_count(content),
            session_id=session_id,
            scope_id=scope_id,
        )
        bucket = self._messages[key]
        bucket.append(message)
        expired = self._drop_expired(session_id, ts, scope_id)
        if expired:
            self._evicted[key].extend(expired)
        bucket = self._messages[key]
        if len(bucket) > self.config.raw_window_turns:
            overflow = len(bucket) - self.config.raw_window_turns
            self._evicted[key].extend(bucket[:overflow])
            del bucket[:overflow]
        return message

    def read_window(
        self,
        session_id: str,
        n: Optional[int] = None,
        scope_id: str = "default",
    ) -> List[Message]:
        """Read recent L0 messages.

        输入:
            session_id: 会话 ID。
            n: 最近消息数量；None 表示全窗口。
            scope_id: 作用域 ID。
        输出:
            list[Message]: 消息副本列表。
        示例:
            示例输入: buffer.read_window("s1", 3, scope_id="t1")
            示例输出: 最近最多 3 条 Message 对象列表。
        """
        key = self._key(session_id, scope_id)
        messages = list(self._messages.get(key, []))
        if n is None:
            return messages
        return messages[-n:]

    def flush_to_l1(
        self,
        session_id: str,
        scope_id: str = "default",
    ) -> List[Message]:
        """Flush the current L0 window for L1 compression.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            list[Message]: 被刷出的消息列表。
        示例:
            示例输入: buffer.flush_to_l1("s1", scope_id="t1")
            示例输出: 当前窗口内 Message 列表，且 L0 对应窗口被清空。
        """
        key = self._key(session_id, scope_id)
        messages = self.read_window(session_id, scope_id=scope_id)
        self._messages[key] = []
        return messages

    def drain_evicted(
        self,
        session_id: str,
        scope_id: str = "default",
    ) -> List[Message]:
        """Return messages evicted by TTL or ring capacity and clear them.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            list[Message]: 本次待补偿压缩的淘汰消息。
        示例:
            示例输入: buffer.drain_evicted("s1", scope_id="t1")
            示例输出: [Message(...), ...]
        """
        key = self._key(session_id, scope_id)
        messages = list(self._evicted.get(key, []))
        self._evicted[key] = []
        return messages

    def token_total(self, session_id: str, scope_id: str = "default") -> int:
        """Return current token usage for a session.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            int: L0 当前 token 估算值。
        示例:
            示例输入: buffer.token_total("s1", scope_id="t1")
            示例输出: 3
        """
        key = self._key(session_id, scope_id)
        return sum(message.token_len for message in self._messages.get(key, []))

    def turn_count(self, session_id: str, scope_id: str = "default") -> int:
        """Return total observed turns for a session.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            int: 已写入轮次。
        示例:
            示例输入: buffer.turn_count("s1", scope_id="t1")
            示例输出: 2
        """
        return self._turns[self._key(session_id, scope_id)]

    def should_compress(self, session_id: str, scope_id: str = "default") -> bool:
        """Check whether L0 should be compressed into L1.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            bool: 是否达到 token 或 K 轮触发条件。
        示例:
            示例输入: buffer.should_compress("s1", scope_id="t1")
            示例输出: True
        """
        turns = self.turn_count(session_id, scope_id)
        return (
            self.token_total(session_id, scope_id)
            > self.config.compression_token_threshold
            or turns % self.config.flush_turns == 0
        )

    def snapshot(
        self,
        scope_id: Optional[str] = None,
    ) -> Dict[str, List[Dict[str, object]]]:
        """Return a debug snapshot of the buffer.

        输入:
            scope_id: 可选作用域 ID；None 返回全部作用域。
        输出:
            dict: session_id 到消息字典列表的映射。
        示例:
            示例输入: buffer.snapshot("t1")
            示例输出: {"s1": [{"role": "user", "content": "hello", ...}]}
        """
        snapshot = {}
        for key, messages in self._messages.items():
            identity = self._identities.get(key)
            if scope_id is not None and (
                identity is None or identity.scope_id != scope_id
            ):
                continue
            display_key = identity.session_id if identity else key
            if (
                identity is not None
                and identity.scope_id != "default"
                and scope_id is None
            ):
                display_key = key
            snapshot[display_key] = [message.to_dict() for message in messages]
        return snapshot

    def active_sessions(self, scope_id: Optional[str] = None) -> List[MemoryIdentity]:
        """Return identities that currently have L0 state.

        输入:
            scope_id: 可选作用域过滤。
        输出:
            list[MemoryIdentity]: 活跃会话身份列表。
        示例:
            示例输入: buffer.active_sessions("t1")
            示例输出: [MemoryIdentity(scope_id="t1", session_id="s1")]
        """
        identities = []
        for key, identity in self._identities.items():
            if scope_id is None or identity.scope_id == scope_id:
                if self._messages.get(key) or self._evicted.get(key):
                    identities.append(identity)
        return identities

    def _drop_expired(
        self,
        session_id: str,
        now_ts: float,
        scope_id: str = "default",
    ) -> List[Message]:
        """Drop messages outside the raw TTL window.

        输入:
            session_id: 会话 ID。
            now_ts: 当前时间戳。
            scope_id: 作用域 ID。
        输出:
            list[Message]: 被 TTL 淘汰的消息。
        示例:
            示例输入: buffer._drop_expired("s1", 100.0, scope_id="t1")
            示例输出: 过期 Message 列表，且这些消息从 session 窗口中移除。
        """
        key = self._key(session_id, scope_id)
        cutoff = now_ts - self.config.raw_ttl_seconds
        expired = [message for message in self._messages[key] if message.ts < cutoff]
        self._messages[key] = [
            message for message in self._messages[key] if message.ts >= cutoff
        ]
        return expired

    def _key(self, session_id: str, scope_id: str = "default") -> str:
        """Build the internal scope-scoped session key.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            str: 内部隔离键。
        示例:
            示例输入: buffer._key("s1", "t1")
            示例输出: "t1:s1"
        """
        identity = MemoryIdentity.from_parts(session_id, scope_id)
        return identity.scoped_session_key()
