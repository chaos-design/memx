"""L0 raw observation model definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .enums import Role


@dataclass(frozen=True)
class MemoryIdentity:
    """Scope/session identity shared by all short-term layers."""

    scope_id: str = "default"
    session_id: str = "default"

    def __post_init__(self) -> None:
        """Validate the identity keys.

        输入:
            self: 记忆身份对象。
        输出:
            None；任一隔离键为空时抛出 ValueError。
        示例:
            示例输入: MemoryIdentity("scope", "session")
            示例输出: MemoryIdentity 对象完成初始化，无异常。
        """
        if not self.scope_id:
            msg = "scope_id must not be empty."
            raise ValueError(msg)
        if not self.session_id:
            msg = "session_id must not be empty."
            raise ValueError(msg)

    @classmethod
    def from_parts(
        cls,
        session_id: str,
        scope_id: str = "default",
    ) -> "MemoryIdentity":
        """Create an identity from common service parameters.

        输入:
            session_id: 会话 ID。
            scope_id: 作用域 ID。
        输出:
            MemoryIdentity: 统一身份对象。
        示例:
            示例输入: MemoryIdentity.from_parts("s1", "scope")
            示例输出: MemoryIdentity(scope_id="scope", session_id="s1")
        """
        return cls(scope_id=scope_id, session_id=session_id)

    def scoped_session_key(self) -> str:
        """Return the storage key for scope-scoped session state.

        约束:
            分隔符为 ":" 且不做转义，因此 scope_id 不得包含 ":"。
            否则 ("a:b", "c") 与 ("a", "b:c") 会得到同一个键 "a:b:c"，
            导致两个会话共享 L0/L1 状态。scope_id 属部署期配置而非请求输入，
            该冲突不会被外部请求触发，但一旦出现作用域命名带冒号即静默串号。

        输入:
            self: 记忆身份对象。
        输出:
            str: 可用于 L0/L1 内部字典的会话隔离键。
        示例:
            示例输入: MemoryIdentity("scope", "s1").scoped_session_key()
            示例输出: "scope:s1"
        """
        if self.scope_id == "default":
            return self.session_id
        return f"{self.scope_id}:{self.session_id}"

    def source_prefix(self) -> str:
        """Return a stable source prefix for evidence IDs.

        输入:
            self: 记忆身份对象。
        输出:
            str: 包含作用域和会话的证据前缀。
        示例:
            示例输入: MemoryIdentity("scope", "s").source_prefix()
            示例输出: "scope:scope:session:s"
        """
        return f"scope:{self.scope_id}:session:{self.session_id}"

    def to_dict(self) -> Dict[str, str]:
        """Serialize identity keys.

        输入:
            self: 记忆身份对象。
        输出:
            dict: scope_id、session_id。
        示例:
            示例输入: MemoryIdentity("scope", "s").to_dict()
            示例输出: {"scope_id": "scope", "session_id": "s"}
        """
        return {
            "scope_id": self.scope_id,
            "session_id": self.session_id,
        }


@dataclass
class Message:
    """Raw message stored in L0."""

    turn_id: int
    role: Role
    content: str
    ts: float
    token_len: int
    session_id: str
    scope_id: str = "default"

    def __post_init__(self) -> None:
        """Validate raw message fields.

        输入:
            self: L0 消息对象。
        输出:
            None；非法字段会抛出 ValueError。
        示例:
            示例输入: Message(1, Role.USER, "hi", 1.0, 1, "s1")
            示例输出: Message 对象完成初始化，无异常。
        """
        if not self.session_id:
            msg = "session_id must not be empty."
            raise ValueError(msg)
        if not self.scope_id:
            msg = "scope_id must not be empty."
            raise ValueError(msg)
        if not self.content:
            msg = "content must not be empty."
            raise ValueError(msg)
        if self.token_len < 0:
            msg = "token_len must be non-negative."
            raise ValueError(msg)

    def identity(self) -> MemoryIdentity:
        """Return the normalized message identity.

        输入:
            self: L0 消息对象。
        输出:
            MemoryIdentity: 该消息所属身份。
        示例:
            示例输入: Message(1, Role.USER, "hi", 1.0, 1, "s1").identity()
            示例输出: MemoryIdentity(scope_id="default", session_id="s1")
        """
        return MemoryIdentity(
            scope_id=self.scope_id,
            session_id=self.session_id,
        )

    def source_id(self) -> str:
        """Return a stable evidence source ID for this message.

        输入:
            self: L0 消息对象。
        输出:
            str: 包含身份与 turn_id 的来源 ID。
        示例:
            示例输入: Message(1, Role.USER, "hi", 1.0, 1, "s1").source_id()
            示例输出: "scope:default:session:s1:turn:1"
        """
        return f"{self.identity().source_prefix()}:turn:{self.turn_id}"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the message into a JSON-compatible dict.

        输入:
            self: L0 消息对象。
        输出:
            dict: 可序列化字段。
        示例:
            示例输入: Message(1, Role.USER, "hi", 1.0, 1, "s1").to_dict()
            示例输出: {"turn_id": 1, "role": "user", "content": "hi", ...}
        """
        return {
            "turn_id": self.turn_id,
            "role": self.role.value,
            "content": self.content,
            "ts": self.ts,
            "token_len": self.token_len,
            "session_id": self.session_id,
            "scope_id": self.scope_id,
        }
