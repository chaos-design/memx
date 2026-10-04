"""File storage for project-local Memory state snapshots."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

from ..config.paths import (
    DEFAULT_MEMORY_DIR,
    ensure_memory_dir,
    project_root,
    to_project_relative,
    validate_memory_dir,
)
from ..constants import SAFE_NAME_PATTERN_TEXT

SAFE_NAME_PATTERN = re.compile(SAFE_NAME_PATTERN_TEXT)


class MemoryFileStore:
    """Project-local JSON store rooted at `.memories`."""

    def __init__(
        self,
        memory_dir: Union[str, Path] = DEFAULT_MEMORY_DIR,
        root: Optional[Path] = None,
    ) -> None:
        """Initialize the Memory file store.

        输入:
            memory_dir: 相对项目根目录的 Memory 数据目录。
            root: 可选项目根目录；None 使用自动解析。
        输出:
            None。
        示例:
            示例输入: MemoryFileStore(".memories/test-suite")
            示例输出: MemoryFileStore 实例，base_dir 指向项目内 .memories/test-suite。
        """
        self.root = (root or project_root()).resolve()
        self.relative_dir = validate_memory_dir(memory_dir)
        self.base_dir = ensure_memory_dir(self.relative_dir, self.root)

    def scope_state_path(self, scope_id: str) -> Path:
        """Return the absolute JSON state path for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            Path: 作用域状态文件绝对路径。
        示例:
            示例输入: store.scope_state_path("scope-a")
            示例输出: Path(".../.memories/scopes/scope-a/memory-state.json")
        """
        scope_key = self._safe_name(scope_id)
        return self.base_dir / "scopes" / scope_key / "memory-state.json"

    def scope_state_relative_path(self, scope_id: str) -> str:
        """Return the project-relative JSON state path for a scope.

        输入:
            scope_id: 作用域 ID。
        输出:
            str: 相对于项目根目录的状态文件路径。
        示例:
            示例输入: store.scope_state_relative_path("scope-a")
            示例输出: ".memories/scopes/scope-a/memory-state.json"
        """
        return to_project_relative(self.scope_state_path(scope_id), self.root)

    def write_scope_state(
        self,
        scope_id: str,
        state: Dict[str, Any],
    ) -> str:
        """Write scope Memory state as JSON.

        输入:
            scope_id: 作用域 ID。
            state: 可 JSON 序列化的 Memory 状态。
        输出:
            str: 写入文件的项目相对路径。
        示例:
            示例输入: store.write_scope_state("scope-a", {"scope_id": "scope-a"})
            示例输出: ".memories/scopes/scope-a/memory-state.json"
        """
        state_path = self.scope_state_path(scope_id)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(state_path)
        return self.scope_state_relative_path(scope_id)

    def read_scope_state(self, scope_id: str) -> Optional[Dict[str, Any]]:
        """Read scope Memory state from JSON.

        输入:
            scope_id: 作用域 ID。
        输出:
            dict | None: 已存储状态；文件不存在时返回 None。
        示例:
            示例输入: store.read_scope_state("scope-a")
            示例输出: {"scope_id": "scope-a", ...} 或 None。
        """
        state_path = self.scope_state_path(scope_id)
        if not state_path.exists():
            return None
        return json.loads(state_path.read_text(encoding="utf-8"))

    def _safe_name(self, value: str) -> str:
        """Convert an external key into a filesystem-safe name.

        输入:
            value: 作用域或会话等外部 key。
        输出:
            str: 可用于目录名的安全字符串。
        示例:
            示例输入: store._safe_name("scope/a")
            示例输出: "scope_a"
        """
        cleaned = SAFE_NAME_PATTERN.sub("_", value).strip("._")
        return cleaned or "default"
