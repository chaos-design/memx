#!/usr/bin/env python3
# coverage: ignore file
"""Standalone runner for the MemX test suite.

Run from the memx project root:
    python3 scripts/run_memory_tests.py
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_REPORT_DIR = ".memories/test_reports"
REQUIRED_MODULES = {
    "pytest": "pytest",
    "pytest_cov": "pytest-cov",
    "ruff": "ruff",
}


@dataclass
class CommandResult:
    """Execution result for one subprocess command."""

    # Human-readable command label, for console and report output.
    name: str

    # Exact command vector passed to subprocess.
    command: List[str]

    # Process exit code; 0 means success.
    returncode: int

    # Combined stdout/stderr text.
    output: str


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    输入:
        argv: 可选命令行参数序列；None 表示读取 sys.argv。
    输出:
        argparse.Namespace: 解析后的参数对象。
    示例:
        示例输入: parse_args(["--skip-install"])
        示例输出: Namespace(skip_install=True, ...)
    """
    parser = argparse.ArgumentParser(
        description="Initialize, load mock data, run Memory tests, and report.",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Do not auto-install missing pytest/pytest-cov/ruff modules.",
    )
    parser.add_argument(
        "--report-dir",
        default=DEFAULT_REPORT_DIR,
        help="Project-relative .memories report directory.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Timeout seconds for each command.",
    )
    parser.add_argument(
        "--pytest-extra-args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Extra arguments appended to the pytest command.",
    )
    return parser.parse_args(argv)


def project_root() -> Path:
    """Return the memx project root path.

    输入:
        无。
    输出:
        Path: memx 项目根目录。
    示例:
        示例输入: project_root()
        示例输出: Path("/.../memx")
    """
    return Path(__file__).resolve().parents[1]


def ensure_project_import_path(repo_root: Path) -> None:
    """Ensure project source and test helpers are importable.

    输入:
        repo_root: 项目根目录。
    输出:
        None；必要时更新 sys.path。
    示例:
        示例输入: ensure_project_import_path(project_root())
        示例输出: None，随后可 import mem。
    """
    for path in (repo_root / "src", repo_root / "tests"):
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)


def resolve_report_dir(report_dir: str, repo_root: Path) -> Path:
    """Resolve the report directory under project `.memories`.

    输入:
        report_dir: 相对项目根目录的报告目录。
        repo_root: 项目根目录。
    输出:
        Path: 解析后的报告目录。
    示例:
        示例输入: resolve_report_dir(".memories/test_reports", project_root())
        示例输出: Path(".../.memories/test_reports")
    """
    ensure_project_import_path(repo_root)
    from mem.config.paths import resolve_project_path, validate_memory_dir

    relative = validate_memory_dir(report_dir)
    return resolve_project_path(relative, repo_root)


def module_available(module_name: str) -> bool:
    """Check whether a Python module can be imported.

    输入:
        module_name: Python import module name。
    输出:
        bool: True 表示当前解释器可导入该模块。
    示例:
        示例输入: module_available("pytest")
        示例输出: True
    """
    return importlib.util.find_spec(module_name) is not None


def run_command(
    name: str,
    command: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
) -> CommandResult:
    """Run a subprocess command and capture combined output.

    输入:
        name: 命令名称。
        command: 命令参数列表。
        cwd: 执行目录。
        env: 环境变量。
        timeout: 超时时间，单位秒。
    输出:
        CommandResult: 命令退出码和输出。
    示例:
        示例输入: run_command("version", ["python3", "--version"], root, env, 30)
        示例输出: CommandResult(returncode=0, output="Python ...")
    """
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            env=dict(env),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        return CommandResult(name, list(command), 124, output + "\nTIMEOUT")
    except OSError as exc:
        return CommandResult(name, list(command), 127, str(exc))
    return CommandResult(name, list(command), completed.returncode, completed.stdout)


def install_package(
    package_name: str,
    repo_root: Path,
    env: Mapping[str, str],
    timeout: int,
) -> CommandResult:
    """Install a missing test dependency into the current user environment.

    输入:
        package_name: pip 包名。
        repo_root: 项目根目录。
        env: 环境变量。
        timeout: 安装命令超时时间。
    输出:
        CommandResult: pip install 执行结果。
    示例:
        示例输入: install_package("pytest", root, env, 180)
        示例输出: CommandResult(name="install pytest", returncode=0, ...)
    """
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--user",
        package_name,
    ]
    return run_command(f"install {package_name}", command, repo_root, env, timeout)


def initialize_environment(repo_root: Path) -> Dict[str, str]:
    """Build the environment used by all test commands.

    输入:
        repo_root: 项目根目录。
    输出:
        dict: 包含 PYTHONPATH 和稳定终端配置的环境变量。
    示例:
        示例输入: initialize_environment(project_root())
        示例输出: {"PYTHONPATH": "src:tests:...", ...}
    """
    env = dict(os.environ)
    python_paths = [
        str(repo_root / "src"),
        str(repo_root / "tests"),
    ]
    existing = env.get("PYTHONPATH")
    if existing:
        python_paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def ensure_dependencies(
    repo_root: Path,
    env: Mapping[str, str],
    skip_install: bool,
    timeout: int,
) -> Tuple[Dict[str, bool], List[CommandResult]]:
    """Ensure required runner dependencies are importable.

    输入:
        repo_root: 项目根目录。
        env: 命令环境。
        skip_install: 是否禁止自动安装。
        timeout: 安装命令超时时间。
    输出:
        tuple: 依赖可用状态和安装命令结果列表。
    示例:
        示例输入: ensure_dependencies(root, env, False, 180)
        示例输出: ({"pytest": True, "ruff": True, ...}, [])
    """
    availability: Dict[str, bool] = {}
    install_results: List[CommandResult] = []
    for module_name, package_name in REQUIRED_MODULES.items():
        available = module_available(module_name)
        if not available and not skip_install:
            result = install_package(package_name, repo_root, env, timeout)
            install_results.append(result)
            importlib.invalidate_caches()
            available = result.returncode == 0 and module_available(module_name)
        availability[module_name] = available
    return availability, install_results


def load_mock_statistics(repo_root: Path) -> Dict[str, Any]:
    """Load mock_conversations and summarize available mock data.

    输入:
        repo_root: 项目根目录。
    输出:
        dict: mock 分组数量、消息数量和场景名称。
    示例:
        示例输入: load_mock_statistics(project_root())
        示例输出: {"groups": {"normal": 2, ...}, "message_count": 262, ...}
    """
    tests_dir = repo_root / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    mock_module = importlib.import_module("mock_conversations")
    groups = mock_module.ALL_MOCK_SCENARIO_GROUPS
    group_counts = {name: len(items) for name, items in groups.items()}
    scenario_names = {
        name: [item["name"] for item in items] for name, items in groups.items()
    }
    message_count = 0
    for group_name in ("normal", "boundary", "qa_personal_preferences"):
        for scenario in groups[group_name]:
            message_count += len(scenario["messages"])
    return {
        "groups": group_counts,
        "scenario_names": scenario_names,
        "message_count": message_count,
        "expected_group_names": sorted(groups),
    }


def build_test_commands(
    pytest_extra_args: Sequence[str],
) -> List[Tuple[str, List[str]]]:
    """Build the commands used to validate the MemX package.

    输入:
        pytest_extra_args: 追加到 pytest 后的参数。
    输出:
        list[tuple]: 命令名称和命令参数。
    示例:
        示例输入: build_test_commands([])
        示例输出: [("ruff check", ["python", "-m", "ruff", ...]), ...]
    """
    pytest_command = [
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "-v",
        "--cov=mem",
        "--cov-report=term-missing",
    ]
    pytest_command.extend(pytest_extra_args)
    return [
        (
            "ruff check",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "src/mem",
                "tests",
                "examples",
                "scripts",
            ],
        ),
        ("pytest", pytest_command),
    ]


def display_command(command: Sequence[str]) -> List[str]:
    """Return a report-friendly command without absolute interpreter paths.

    输入:
        command: 实际执行的命令参数。
    输出:
        list[str]: 适合写入报告的命令参数。
    示例:
        示例输入: display_command([sys.executable, "-m", "pytest"])
        示例输出: ["python3", "-m", "pytest"]
    """
    if command and command[0] == sys.executable:
        return ["python3", *command[1:]]
    return list(command)


def parse_pytest_summary(output: str) -> Dict[str, Any]:
    """Extract test and coverage statistics from pytest output.

    输入:
        output: pytest 命令输出。
    输出:
        dict: passed、failed、errors、coverage_percent 等统计。
    示例:
        示例输入: parse_pytest_summary("15 passed ... TOTAL ... 96%")
        示例输出: {"passed": 15, "coverage_percent": 96, ...}
    """
    stats: Dict[str, Any] = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "coverage_percent": None,
    }
    summary_match = re.search(r"=+ (?P<summary>.+?) in [0-9.]+s =+", output)
    if summary_match:
        summary = summary_match.group("summary")
        for count, label in re.findall(
            r"(\d+) (passed|failed|error|errors|skipped)",
            summary,
        ):
            normalized = "errors" if label in {"error", "errors"} else label
            stats[normalized] = int(count)
    coverage_match = re.search(r"TOTAL\s+(?:\d+\s+)+(?P<coverage>\d+)%", output)
    if coverage_match:
        stats["coverage_percent"] = int(coverage_match.group("coverage"))
    return stats


def tail_text(text: str, max_chars: int = 4_000) -> str:
    """Return the tail of a long command output.

    输入:
        text: 原始输出。
        max_chars: 最大保留字符数。
    输出:
        str: 尾部输出文本。
    示例:
        示例输入: tail_text("abcdef", 3)
        示例输出: "def"
    """
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def scrub_project_paths(text: str, repo_root: Path) -> str:
    """Replace project absolute paths in command output with relative markers.

    输入:
        text: 命令输出。
        repo_root: 项目根目录。
    输出:
        str: 项目路径已归一为 "." 的输出。
    示例:
        示例输入: scrub_project_paths("/repo/tests", Path("/repo"))
        示例输出: "./tests"
    """
    return text.replace(str(repo_root), ".")


def render_markdown_report(report: Mapping[str, Any]) -> str:
    """Render the JSON-compatible report as Markdown.

    输入:
        report: 测试执行报告数据。
    输出:
        str: Markdown 报告正文。
    示例:
        示例输入: render_markdown_report({"status": "pass", ...})
        示例输出: "# Memory Module Test Report\n..."
    """
    lines = [
        "# Memory Module Test Report",
        "",
        f"- status: {report['status']}",
        f"- generated_at: {report['generated_at']}",
        f"- python: {report['python']}",
        f"- repo_root: {report['repo_root']}",
        "",
        "## Mock Data",
        "",
        f"- groups: `{json.dumps(report['mock_data']['groups'], ensure_ascii=False)}`",
        f"- message_count: {report['mock_data']['message_count']}",
        "",
        "## Test Summary",
        "",
        f"- pytest: `{json.dumps(report['pytest_summary'], ensure_ascii=False)}`",
        "",
        "## Commands",
        "",
        "| name | exit_code | command |",
        "| --- | ---: | --- |",
    ]
    for result in report["commands"]:
        command = " ".join(result["command"])
        lines.append(f"| {result['name']} | {result['returncode']} | `{command}` |")
    lines.extend(["", "## Report Files", ""])
    for key, value in report["report_files"].items():
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines) + "\n"


def write_reports(
    report: Dict[str, Any],
    report_dir: Path,
    repo_root: Path,
) -> Dict[str, str]:
    """Write JSON and Markdown reports to disk.

    输入:
        report: 测试报告数据。
        report_dir: 报告输出目录。
        repo_root: 项目根目录。
    输出:
        dict: json 和 markdown 报告路径。
    示例:
        示例输入: write_reports(report, Path(".memories/test_reports"), root)
        示例输出: {"json": ".memories/test_reports/memory-test-report.json", ...}
    """
    from mem.config.paths import to_project_relative

    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "memory-test-report.json"
    markdown_path = report_dir / "memory-test-report.md"
    report["report_files"] = {
        "json": to_project_relative(json_path, repo_root),
        "markdown": to_project_relative(markdown_path, repo_root),
    }
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    return report["report_files"]


def print_console_summary(report: Mapping[str, Any]) -> None:
    """Print a concise console summary.

    输入:
        report: 测试报告数据。
    输出:
        None；摘要写入标准输出。
    示例:
        示例输入: print_console_summary(report)
        示例输出: 控制台显示状态、mock 统计和报告路径。
    """
    print("\nMemX test run")
    print(f"status: {report['status']}")
    print(f"mock_groups: {report['mock_data']['groups']}")
    print(f"mock_messages: {report['mock_data']['message_count']}")
    print(f"pytest_summary: {report['pytest_summary']}")
    for result in report["commands"]:
        print(f"{result['name']}: exit_code={result['returncode']}")
    for key, path in report["report_files"].items():
        print(f"{key}_report: {path}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run environment setup, mock loading, tests, and report generation.

    输入:
        argv: 可选命令行参数序列。
    输出:
        int: 进程退出码，0 表示全部通过。
    示例:
        示例输入: main(["--report-dir", ".memories/custom-report"])
        示例输出: 0
    """
    args = parse_args(argv)
    repo_root = project_root()
    ensure_project_import_path(repo_root)
    report_dir = resolve_report_dir(args.report_dir, repo_root)
    env = initialize_environment(repo_root)
    dependency_status, install_results = ensure_dependencies(
        repo_root=repo_root,
        env=env,
        skip_install=args.skip_install,
        timeout=args.timeout,
    )
    mock_data = load_mock_statistics(repo_root)

    command_results: List[CommandResult] = list(install_results)
    dependencies_ready = all(dependency_status.values())
    if dependencies_ready:
        for name, command in build_test_commands(args.pytest_extra_args):
            command_results.append(
                run_command(name, command, repo_root, env, args.timeout)
            )

    pytest_output = ""
    for result in command_results:
        if result.name == "pytest":
            pytest_output = result.output
            break
    pytest_summary = parse_pytest_summary(pytest_output)
    commands_ok = command_results and all(
        result.returncode == 0 for result in command_results
    )
    status = "pass" if dependencies_ready and commands_ok else "fail"
    report: Dict[str, Any] = {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "repo_root": ".",
        "dependency_status": dependency_status,
        "mock_data": mock_data,
        "pytest_summary": pytest_summary,
        "commands": [
            {
                "name": result.name,
                "command": display_command(result.command),
                "returncode": result.returncode,
                "output_tail": tail_text(scrub_project_paths(result.output, repo_root)),
            }
            for result in command_results
        ],
        "report_files": {},
    }
    write_reports(report, report_dir, repo_root)
    print_console_summary(report)
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
