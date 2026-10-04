"""Project-relative path helpers for Memory storage."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional, Union

DEFAULT_MEMORY_DIR = ".memories"


def project_root() -> Path:
    """Return the project root for the MemX package.

    输入:
        无。
    输出:
        Path: 当前项目根目录的绝对路径。
    示例:
        示例输入: project_root()
        示例输出: Path(".../memx")
    """
    return Path(__file__).resolve().parents[3]


def _as_relative_posix_path(path: Union[str, Path]) -> PurePosixPath:
    """Normalize a path string into a POSIX-style relative path.

    输入:
        path: 待校验路径。
    输出:
        PurePosixPath: 统一分隔符后的相对路径。
    示例:
        示例输入: _as_relative_posix_path(".memories\\\\tests")
        示例输出: PurePosixPath(".memories/tests")
    """
    path_text = str(path).strip()
    if not path_text:
        msg = "path must not be empty."
        raise ValueError(msg)
    return PurePosixPath(path_text.replace("\\", "/"))


def validate_relative_path(path: Union[str, Path]) -> PurePosixPath:
    """Validate that a path is project-relative and stays inside the project.

    输入:
        path: 待校验路径，必须是相对路径。
    输出:
        PurePosixPath: 校验后的相对路径。
    示例:
        示例输入: validate_relative_path(".memories/test")
        示例输出: PurePosixPath(".memories/test")
    """
    path_text = str(path).strip()
    normalized = _as_relative_posix_path(path_text)
    windows_path = PureWindowsPath(path_text)
    if normalized.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        msg = "path must be relative to project root."
        raise ValueError(msg)
    if any(part in {"..", ""} for part in normalized.parts):
        msg = "path must not contain empty or parent traversal segments."
        raise ValueError(msg)
    return normalized


def validate_memory_dir(memory_dir: Union[str, Path]) -> PurePosixPath:
    """Validate that Memory data is stored under the project .memories folder.

    输入:
        memory_dir: Memory 数据目录，必须位于 .memories 下。
    输出:
        PurePosixPath: 校验后的相对目录。
    示例:
        示例输入: validate_memory_dir(".memories/test-suite")
        示例输出: PurePosixPath(".memories/test-suite")
    """
    relative = validate_relative_path(memory_dir)
    if not relative.parts or relative.parts[0] != DEFAULT_MEMORY_DIR:
        msg = "memory_dir must be inside the project .memories directory."
        raise ValueError(msg)
    return relative


def resolve_project_path(
    relative_path: Union[str, Path],
    root: Optional[Path] = None,
) -> Path:
    """Resolve a validated relative path under the project root.

    输入:
        relative_path: 相对于项目根目录的路径。
        root: 可选项目根目录；None 使用自动解析结果。
    输出:
        Path: 解析后的绝对路径。
    示例:
        示例输入: resolve_project_path(".memories")
        示例输出: Path(".../memx/.memories")
    """
    relative = validate_relative_path(relative_path)
    root_path = (root or project_root()).resolve()
    resolved = (root_path / Path(*relative.parts)).resolve()
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        msg = "resolved path escapes project root."
        raise ValueError(msg) from exc
    return resolved


def ensure_memory_dir(
    memory_dir: Union[str, Path] = DEFAULT_MEMORY_DIR,
    root: Optional[Path] = None,
) -> Path:
    """Create and return the project .memories directory.

    输入:
        memory_dir: Memory 数据目录，必须位于 .memories 下。
        root: 可选项目根目录。
    输出:
        Path: 已创建的绝对目录路径。
    示例:
        示例输入: ensure_memory_dir(".memories/test-suite")
        示例输出: Path(".../memx/.memories/test-suite")
    """
    relative = validate_memory_dir(memory_dir)
    path = resolve_project_path(relative, root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def to_project_relative(path: Union[str, Path], root: Optional[Path] = None) -> str:
    """Convert a project-contained path into a POSIX relative string.

    输入:
        path: 项目内路径。
        root: 可选项目根目录。
    输出:
        str: 相对于项目根目录的 POSIX 风格路径。
    示例:
        示例输入: to_project_relative(project_root() / ".memories")
        示例输出: ".memories"
    """
    root_path = (root or project_root()).resolve()
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(root_path)
    except ValueError as exc:
        msg = "path is not inside project root."
        raise ValueError(msg) from exc
    return relative.as_posix() or "."
