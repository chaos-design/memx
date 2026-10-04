"""Persistence coordination for AgentMemory state snapshots."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ..memory.ports import SnapshotStorePort


class PersistenceManager:
    """Track dirty scopes and make snapshot persistence explicit."""

    def __init__(self, store: SnapshotStorePort) -> None:
        """Initialize the persistence manager.

        输入:
            store: 项目本地或生产快照存储 Port。
        输出:
            None。
        示例:
            示例输入: PersistenceManager(MemoryFileStore(".memories/test"))
            示例输出: PersistenceManager 实例，dirty 集合为空。
        """
        self.store = store
        self._dirty_scopes: set[str] = set()
        self._last_paths: Dict[str, str] = {}

    def mark_dirty(self, scope_id: str) -> None:
        """Mark a scope state as dirty.

        输入:
            scope_id: 作用域 ID。
        输出:
            None。
        示例:
            示例输入: manager.mark_dirty("scope")
            示例输出: None，scope 进入待持久化集合。
        """
        self._dirty_scopes.add(scope_id)

    def flush_scope(self, scope_id: str, state: Dict[str, Any]) -> str:
        """Persist one scope state and clear its dirty flag.

        输入:
            scope_id: 作用域 ID。
            state: 可 JSON 序列化的作用域状态。
        输出:
            str: 项目相对状态文件路径。
        示例:
            示例输入: manager.flush_scope("scope", {"scope_id": "scope"})
            示例输出: ".memories/scopes/scope/memory-state.json"
        """
        path = self.store.write_scope_state(scope_id, state)
        self._dirty_scopes.discard(scope_id)
        self._last_paths[scope_id] = path
        return path

    def flush_many(
        self,
        scope_ids: Iterable[str],
        states: Dict[str, Dict[str, Any]],
    ) -> Dict[str, str]:
        """Persist multiple scope states.

        输入:
            scope_ids: 需要持久化的作用域 ID 序列。
            states: scope_id 到状态快照的映射。
        输出:
            dict: scope_id 到项目相对路径的映射。
        示例:
            示例输入: manager.flush_many(["t"], {"t": {"scope_id": "t"}})
            示例输出: {"t": ".memories/scopes/t/memory-state.json"}
        """
        return {
            scope_id: self.flush_scope(scope_id, states[scope_id])
            for scope_id in scope_ids
            if scope_id in states
        }

    def is_dirty(self, scope_id: str) -> bool:
        """Return whether a scope has unflushed changes.

        输入:
            scope_id: 作用域 ID。
        输出:
            bool: True 表示存在待持久化修改。
        示例:
            示例输入: manager.is_dirty("scope")
            示例输出: True
        """
        return scope_id in self._dirty_scopes

    def dirty_scopes(self) -> List[str]:
        """Return sorted dirty scope IDs.

        输入:
            self: 持久化管理器。
        输出:
            list[str]: 待持久化作用域 ID。
        示例:
            示例输入: manager.dirty_scopes()
            示例输出: ["scope-a", "scope-b"]
        """
        return sorted(self._dirty_scopes)

    def last_path(self, scope_id: str) -> Optional[str]:
        """Return the latest persisted path for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            str | None: 最近一次写入路径。
        示例:
            示例输入: manager.last_path("scope")
            示例输出: ".memories/scopes/scope/memory-state.json" 或 None。
        """
        return self._last_paths.get(scope_id)

    def stats(self, scope_id: str) -> Dict[str, object]:
        """Return persistence diagnostics for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            dict: dirty 标记和最近写入路径。
        示例:
            示例输入: manager.stats("scope")
            示例输出: {"dirty": True, "last_path": "..."}
        """
        return {
            "dirty": self.is_dirty(scope_id),
            "last_path": self.last_path(scope_id),
            "dirty_scopes": self.dirty_scopes(),
        }
