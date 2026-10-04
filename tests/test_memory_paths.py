"""Path resolution and project-local Memory storage tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from mem import AgentMemory, MemoryConfig
from mem.config.paths import (
    DEFAULT_MEMORY_DIR,
    ensure_memory_dir,
    resolve_project_path,
    validate_memory_dir,
    validate_relative_path,
)


def test_relative_memory_path_validation_accepts_project_memories() -> None:
    """Validate allowed Memory paths remain project-relative.

    输入:
        无；测试使用项目相对路径。
    输出:
        None；断言 `.memories` 下路径可通过校验并正确解析。
    示例:
        示例输入: pytest tests/test_memory_paths.py
        示例输出: 相对路径校验通过。
    """
    memory_dir = ".memories/path-validation"
    resolved = resolve_project_path(memory_dir)

    assert validate_relative_path(memory_dir).as_posix() == memory_dir
    assert validate_memory_dir(memory_dir).as_posix() == memory_dir
    assert not Path(memory_dir).is_absolute()
    assert resolved.name == "path-validation"


@pytest.mark.parametrize(
    "path_value",
    [
        pytest.param("memory-outside", id="outside_memories_dir"),
        pytest.param("../.memories", id="parent_traversal"),
        pytest.param(".memories/../outside", id="nested_parent_traversal"),
        pytest.param("C:" + "/agent-library/.memories", id="windows_drive_absolute"),
        pytest.param(
            "\\\\" + "server\\share\\.memories",
            id="windows_unc_absolute",
        ),
    ],
)
def test_memory_path_validation_rejects_invalid_paths(path_value: str) -> None:
    """Validate absolute, traversal, and non-.memories paths are rejected.

    输入:
        path_value: 待拒绝的路径字符串。
    输出:
        None；断言路径校验抛出 ValueError。
    示例:
        示例输入: test_memory_path_validation_rejects_invalid_paths("../.memories")
        示例输出: ValueError 被捕获。
    """
    with pytest.raises(ValueError):
        validate_memory_dir(path_value)


def test_agent_memory_persists_state_under_project_memories() -> None:
    """Verify AgentMemory writes and reads data under `.memories`.

    输入:
        无；测试内部使用 `.memories/path-storage-suite` 相对目录。
    输出:
        None；断言状态文件路径相对、文件存在、内容可读。
    示例:
        示例输入: pytest tests/test_memory_paths.py
        示例输出: Memory 状态成功写入并读取。
    """
    memory_dir = ".memories/path-storage-suite"
    scope_id = "scope/path-storage"
    session_id = "session-path-storage"
    storage_root = Path(memory_dir)
    shutil.rmtree(storage_root, ignore_errors=True)
    try:
        memory = AgentMemory(
            MemoryConfig(
                memory_dir=memory_dir,
                flush_turns=1,
                reflect_importance_threshold=1,
            )
        )
        observed = memory.observe(
            session_id=session_id,
            msg={
                "role": "user",
                "content": "记住 path.storage=relative",
                "ts": 1_900_000_001.0,
            },
            scope_id=scope_id,
        )
        reflected = memory.reflect(scope_id=scope_id, force=True)
        storage_path = observed["storage_path"]
        state = memory.read_stored_state(scope_id)

        assert storage_path.startswith(f"{DEFAULT_MEMORY_DIR}/")
        assert reflected["storage_path"] == storage_path
        assert not Path(storage_path).is_absolute()
        assert Path(storage_path).exists()
        assert state is not None
        assert state["scope_id"] == scope_id
        assert state["memory_dir"] == memory_dir
        assert any(
            fact["fact_key"] == "path.storage" and fact["value"] == "relative"
            for fact in state["l3"]["facts"]
        )
    finally:
        shutil.rmtree(storage_root, ignore_errors=True)


def test_ensure_memory_dir_creates_relative_project_directory() -> None:
    """Verify `.memories` directories can be created from relative paths.

    输入:
        无；测试内部使用 `.memories/path-create-suite`。
    输出:
        None；断言目录被正确创建在项目根下。
    示例:
        示例输入: ensure_memory_dir(".memories/path-create-suite")
        示例输出: 目录存在。
    """
    memory_dir = ".memories/path-create-suite"
    storage_root = Path(memory_dir)
    shutil.rmtree(storage_root, ignore_errors=True)
    try:
        created = ensure_memory_dir(memory_dir)
        assert created.name == "path-create-suite"
        assert storage_root.exists()
        assert storage_root.is_dir()
    finally:
        shutil.rmtree(storage_root, ignore_errors=True)
