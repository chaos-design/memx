"""Tests for the packaged MemX CLI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

from mem import cli


def _read_json_object(text: str) -> Dict[str, Any]:
    """Parse one JSON object from captured CLI output.

    输入:
        text: CLI 输出文本。
    输出:
        dict: 解析后的 JSON 对象。
    示例:
        示例输入: _read_json_object('{"ok": true}')
        示例输出: {"ok": True}
    """
    return json.loads(text)


def _run_cli(argv: List[str], capsys: Any) -> Dict[str, Any]:
    """Run mem.cli.main and return the parsed JSON payload.

    输入:
        argv: CLI 参数列表。
        capsys: pytest output capture fixture。
    输出:
        dict: CLI JSON 输出。
    示例:
        示例输入: _run_cli(["snapshot"], capsys)
        示例输出: {"ok": True, "command": "snapshot", ...}
    """
    exit_code = cli.main(argv)
    captured = capsys.readouterr()
    output = captured.out if exit_code == 0 else captured.err
    parsed = _read_json_object(output)
    assert exit_code == (0 if parsed["ok"] else 1)
    return parsed


def _base_args(memory_dir: str, scope_id: str = "mem-cli-test") -> List[str]:
    """Return shared CLI arguments for isolated test memory.

    输入:
        memory_dir: `.memories` 下的测试目录。
        scope_id: 测试作用域 ID。
    输出:
        list[str]: 可复用的 CLI 参数。
    示例:
        示例输入: _base_args(".memories/test")
        示例输出: ["--memory-dir", ".memories/test", ...]
    """
    return [
        "--memory-dir",
        memory_dir,
        "--scope-id",
        scope_id,
        "--session-id",
        "session-a",
    ]


def test_cli_subcommands_persist_restore_and_recall(capsys: Any) -> None:
    """Verify packaged subcommands persist and restore memory across processes.

    输入:
        capsys: pytest output capture fixture。
    输出:
        None；断言 memorize、reflect、recall、context、graph、snapshot 均可串联。
    示例:
        示例输入: pytest tests/test_cli.py::test_cli_subcommands_persist_restore...
        示例输出: 测试通过。
    """
    memory_dir = ".memories/mem-cli-test-restore"
    scope_id = "mem-cli-restore"
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        args = _base_args(memory_dir, scope_id)
        observed = _run_cli(
            args + ["observe", "user", "记住", "cli.observe=ok"],
            capsys,
        )
        memorized = _run_cli(
            args + ["memorize", "记住", "cli.lang_pref=zh", "--importance", "9"],
            capsys,
        )
        reflected = _run_cli(args + ["reflect", "--force"], capsys)
        recalled = _run_cli(args + ["recall", "cli.lang_pref", "-k", "3"], capsys)
        retrieval_fts5 = _run_cli(
            args + ["retrieval", "fts5", "cli.lang_pref", "-k", "3"],
            capsys,
        )
        retrieval_keywords = _run_cli(
            args + ["retrieval", "keywords", "cli.lang_pref", "-k", "3"],
            capsys,
        )
        retrieval_rerank = _run_cli(
            args + ["retrieval", "rerank", "cli.lang_pref", "-k", "3"],
            capsys,
        )
        retrieval_relevance = _run_cli(
            args
            + [
                "retrieval",
                "relevance",
                "cli.lang_pref",
                "--mem-id",
                memorized["payload"]["mem_id"],
            ],
            capsys,
        )
        retrieval_score = _run_cli(
            args
            + [
                "retrieval",
                "score",
                "cli.lang_pref",
                "--all-scopes",
                "-k",
                "3",
            ],
            capsys,
        )
        context = _run_cli(args + ["context", "cli.lang_pref"], capsys)
        graph = _run_cli(args + ["graph", "query", "cli", "-k", "5"], capsys)
        snapshot = _run_cli(args + ["snapshot"], capsys)
        state = _run_cli(args + ["state"], capsys)

        assert observed["payload"]["promoted"]
        assert memorized["payload"]["mem_id"]
        assert reflected["payload"]["n_facts"] >= 1
        assert any(
            fact["fact_key"] == "cli.lang_pref"
            for fact in recalled["payload"]["facts"]
        )
        assert retrieval_fts5["payload"]["results"]
        assert retrieval_fts5["payload"]["engine"] == "hybrid_rrf"
        assert "related" in retrieval_fts5["payload"]
        assert retrieval_keywords["payload"]["results"][0]["keyword_overlap"] >= 1
        assert retrieval_rerank["payload"]["final"]
        assert retrieval_relevance["payload"]["results"][0]["scores"][
            "passes_relevance"
        ]
        assert retrieval_score["payload"]["score_model"] == "F2"
        assert "Facts:" in context["payload"]["context"]
        assert graph["payload"]["nodes"]
        assert snapshot["payload"]["loaded_state"]["l2_records"] >= 1
        assert snapshot["payload"]["l3_facts"] >= 1
        assert state["payload"]["exists"] is True
        assert state["payload"]["l2_records"] >= 1
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)


def test_cli_update_forget_maintenance_and_diagnostics(capsys: Any) -> None:
    """Verify update, forget, maintenance, diagnostics, and parser errors.

    输入:
        capsys: pytest output capture fixture。
    输出:
        None；断言核心运维命令和失败路径输出稳定。
    示例:
        示例输入: pytest tests/test_cli.py::test_cli_update_forget...
        示例输出: 测试通过。
    """
    memory_dir = ".memories/mem-cli-test-update"
    scope_id = "mem-cli-update"
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        args = _base_args(memory_dir, scope_id)
        memorized = _run_cli(args + ["memorize", "记住", "cli.topic=memory"], capsys)
        mem_id = memorized["payload"]["mem_id"]

        updated = _run_cli(
            args + ["update", "mem", mem_id, "updated", "CLI", "memory"],
            capsys,
        )
        searched = _run_cli(args + ["search", "updated", "-k", "3"], capsys)
        fact = _run_cli(
            args
            + [
                "update",
                "fact",
                "cli.topic",
                "memory",
                "--confidence",
                "0.95",
            ],
            capsys,
        )
        maintenance = _run_cli(
            args + ["maintenance", "run", "consolidate", "forget", "--force-reflect"],
            capsys,
        )
        diagnostics = _run_cli(args + ["diagnostics"], capsys)
        forgotten = _run_cli(args + ["forget", "hard", mem_id, "--force"], capsys)
        snapshot = _run_cli(args + ["snapshot"], capsys)

        assert updated["payload"]["action"] == "updated"
        assert searched["payload"]["episodes"][0]["text"] == "updated CLI memory"
        assert fact["payload"]["action"] == "created"
        assert set(maintenance["payload"]["tasks"]) == {"consolidate", "forget"}
        assert diagnostics["payload"]["profile"] == "memory"
        assert forgotten["payload"]["deleted"] == 1
        assert snapshot["payload"]["l2_deleted"] == 1

        failed = _run_cli(args + ["forget", "hard"], capsys)
        assert failed["ok"] is False
        assert failed["payload"]["error_type"] == "CliError"
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)


def test_cli_config_commands_use_hms_json(capsys: Any, tmp_path: Path) -> None:
    """Verify config show/set commands validate and persist hms.json updates.

    输入:
        capsys: pytest output capture fixture。
        tmp_path: pytest temporary directory fixture。
    输出:
        None；断言配置写入和有效配置读取正常。
    示例:
        示例输入: pytest tests/test_cli.py::test_cli_config_commands_use_hms_json
        示例输出: 测试通过。
    """
    config_path = tmp_path / "hms.json"

    updated = _run_cli(
        [
            "--config",
            str(config_path),
            "config",
            "set",
            "max_recall_k=7",
            "persist_on_write=false",
        ],
        capsys,
    )
    effective = _run_cli(
        ["--config", str(config_path), "config", "show", "--effective"],
        capsys,
    )

    assert updated["payload"]["max_recall_k"] == 7
    assert updated["payload"]["persist_on_write"] is False
    assert effective["payload"]["max_recall_k"] == 7
    assert effective["payload"]["persist_on_write"] is False
