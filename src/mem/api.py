"""Root HumanMem API entry point."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .adapters import MemoryBackendBundle
from .agents.service import AgentMemory as _AgentMemory
from .config.loader import load_memory_config
from .config.settings import MemoryConfig
from .constants import FORGET_MODE_DECAY, PROJECT_MEMORY_SCOPE_ID
from .scheduler import MaintenanceTaskManager


class HumanMem:
    """Application-level API wrapper around AgentMemory."""

    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        backend: Optional[MemoryBackendBundle] = None,
    ) -> None:
        """Initialize the HumanMem API entry point.

        输入:
            config: 可选 MemoryConfig；None 时读取 hms.json。
            backend: 可选后端组合。
        输出:
            None。
        示例:
            示例输入: HumanMem(MemoryConfig(flush_turns=1))
            示例输出: HumanMem 实例，可调用 memorize/recall。
        """
        self.memory = _AgentMemory(config=config, backend=backend)
        self._scope_id = PROJECT_MEMORY_SCOPE_ID
        self._maintenance_manager = MaintenanceTaskManager(
            self.memory,
            scope_id=self._scope_id,
        )

    @classmethod
    def from_config(
        cls,
        path: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> "HumanMem":
        """Create HumanMem from hms.json and overrides.

        输入:
            path: 可选 hms.json 路径。
            overrides: 显式配置覆盖。
        输出:
            HumanMem: API 入口实例。
        示例:
            示例输入: HumanMem.from_config(overrides={"max_recall_k": 10})
            示例输出: HumanMem(...)
        """
        return cls(load_memory_config(path=path, overrides=overrides))

    def observe(
        self,
        session_id: str,
        msg: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Observe one message through the memory pipeline.

        输入:
            session_id: 会话 ID。
            msg: role/content 消息字典。
        输出:
            dict: observe 结果。
        示例:
            示例输入: api.observe("s1", {"role": "user", "content": "记住 x"})
            示例输出: {"promoted": [...], ...}
        """
        return self.memory.observe(session_id, msg, self._project_scope_id())

    def memorize(
        self,
        session_id: str,
        text: str,
        importance: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Explicitly memorize text.

        输入:
            session_id: 会话 ID。
            text: 记忆正文。
            importance: 可选重要性。
        输出:
            dict: memorize 结果。
        示例:
            示例输入: api.memorize("s1", "记住 user.lang=zh")
            示例输出: {"mem_id": "...", "importance": 8}
        """
        return self.memory.memorize(
            session_id,
            text,
            self._project_scope_id(),
            importance,
        )

    def recall(
        self,
        session_id: str,
        query: str,
        k: int = 8,
        entities: Optional[List[str]] = None,
        include_archived: bool = True,
    ) -> Dict[str, Any]:
        """Recall memory context.

        输入:
            session_id: 会话 ID。
            query: 查询文本。
            k: 返回数量。
            entities: 可选实体列表。
            include_archived: 是否包含 archived。
        输出:
            dict: recall 结果。
        示例:
            示例输入: api.recall("s1", "语言偏好", k=3)
            示例输出: {"facts": [...], "episodes": [...]}
        """
        return self.memory.recall(
            session_id=session_id,
            query=query,
            k=k,
            entities=entities,
            scope_id=self._project_scope_id(),
            include_archived=include_archived,
        )

    def search(
        self,
        session_id: str,
        query: str,
        k: int = 8,
    ) -> Dict[str, Any]:
        """Search active memory records.

        输入:
            session_id: 会话 ID。
            query: 查询文本。
            k: 返回数量。
        输出:
            dict: search 结果。
        示例:
            示例输入: api.search("s1", "Agent")
            示例输出: {"facts": [...], "episodes": [...]}
        """
        return self.memory.search(session_id, query, self._project_scope_id(), k)

    def update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update an L2 memory or L3 fact.

        输入:
            payload: 更新载荷。
        输出:
            dict: update 结果。
        示例:
            示例输入: api.update({"mem_id": "m1", "text": "new"})
            示例输出: {"mem_id": "m1", "action": "updated"}
        """
        scoped_payload = dict(payload)
        scoped_payload["scope_id"] = self._project_scope_id()
        return self.memory.update(scoped_payload)

    def forget(
        self,
        mode: str = FORGET_MODE_DECAY,
        mem_id: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Forget memory using explicit modes.

        输入:
            mode: decay、hard 或 expire。
            mem_id: hard 模式目标 ID。
            force: 是否强制删除受保护记忆。
        输出:
            dict: forget 结果。
        示例:
            示例输入: api.forget(mode="hard", mem_id="m1", force=True)
            示例输出: {"deleted": 1, "mem_id": "m1"}
        """
        return self.memory.forget(self._project_scope_id(), mode, mem_id, force)

    def reflect(
        self,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Run memory consolidation.

        输入:
            force: 是否强制整理。
        输出:
            dict: reflect 结果。
        示例:
            示例输入: api.reflect(force=True)
            示例输出: {"n_facts": 1, "n_insights": 1, ...}
        """
        return self.memory.reflect(self._project_scope_id(), force)

    def maintenance(
        self,
        tasks: Optional[List[str]] = None,
        force_reflect: bool = False,
    ) -> Dict[str, Any]:
        """Run scheduled maintenance tasks once.

        输入:
            tasks: 可选任务名列表。
            force_reflect: 是否强制整理。
        输出:
            dict: maintenance 结果。
        示例:
            示例输入: api.maintenance(tasks=["consolidate"])
            示例输出: {"scope_id": "human_mem_project", "tasks": {...}}
        """
        return self._maintenance_manager.run_once(
            tasks=tasks,
            force_reflect=force_reflect,
        )

    def scheduler_status(self) -> Dict[str, Any]:
        """Return current scheduler task state.

        输入:
            self: HumanMem instance.
        输出:
            dict: scheduler status and task state.
        示例:
            示例输入: api.scheduler_status()
            示例输出: {"status": "idle", "tasks": {...}}
        """
        return self._maintenance_manager.status()

    def get_context(
        self,
        session_id: str,
        query: Optional[str] = None,
    ) -> str:
        """Build prompt-ready memory context.

        输入:
            session_id: 会话 ID。
            query: 可选查询。
        输出:
            str: prompt context。
        示例:
            示例输入: api.get_context("s1", "偏好")
            示例输出: "Conversation Summary: ..."
        """
        return self.memory.get_context(
            session_id,
            query,
            self._project_scope_id(),
        )

    def flush(self) -> str:
        """Flush the project memory state.

        输入:
            无。
        输出:
            str: 写入路径。
        示例:
            示例输入: api.flush()
            示例输出: ".memories/scopes/human_mem_project/memory-state.json"
        """
        return self.memory.flush(self._project_scope_id())

    def read_stored_state(self) -> Optional[Dict[str, Any]]:
        """Read persisted memory state.

        输入:
            无。
        输出:
            dict | None: 已存储状态。
        示例:
            示例输入: api.read_stored_state()
            示例输出: {"scope_id": "human_mem_project", ...} 或 None。
        """
        return self.memory.read_stored_state(self._project_scope_id())

    def architecture_snapshot(self) -> Dict[str, Any]:
        """Return a cross-layer architecture snapshot.

        输入:
            无。
        输出:
            dict: 架构快照。
        示例:
            示例输入: api.architecture_snapshot()
            示例输出: {"scope_id": "human_mem_project", "l2": {...}}
        """
        return self.memory.architecture_snapshot(self._project_scope_id())

    def _project_scope_id(self) -> str:
        """Return the single internal project memory scope.

        输入:
            self: HumanMem instance.
        输出:
            str: internal project scope identifier.
        示例:
            示例输入: api._project_scope_id()
            示例输出: "human_mem_project"
        """
        return self._scope_id


__all__ = ["HumanMem"]
