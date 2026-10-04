"""Tests for the interactive MemX debugging CLI."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

import mem_cli


def _read_json_objects(text: str) -> List[Dict[str, Any]]:
    """Parse JSON objects emitted by the CLI output stream.

    输入:
        text: CLI 输出的 JSON 文本，可能包含多个对象。
    输出:
        list[dict]: 解析后的 JSON 对象列表。
    示例:
        示例输入: _read_json_objects('{"ok": true}\\n')
        示例输出: [{"ok": True}]
    """
    decoder = json.JSONDecoder()
    objects: List[Dict[str, Any]] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        item, end = decoder.raw_decode(text, index)
        objects.append(item)
        index = end
    return objects


def test_memory_cli_scripted_commands_cover_core_capabilities() -> None:
    """Verify scripted CLI commands exercise observe, recall, update, and forget.

    输入:
        无；测试内部创建 MemoryCliSession。
    输出:
        None；断言核心命令均返回成功并产生可检索事实。
    示例:
        示例输入: pytest tests/test_mem_cli.py
        示例输出: 脚本化 CLI 核心能力测试通过。
    """
    memory_dir = ".memories/mem-cli-test-core"
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        session = mem_cli.MemoryCliSession(
            config=mem_cli.build_memory_config(memory_dir),
        )

        observed = session.run_command(
            "observe user 记住 cli.lang_pref=zh，语言偏好是中文"
        )
        reflected = session.run_command("reflect force")
        recalled = session.run_command("recall cli.lang_pref 5")
        searched = session.run_command("search 中文 5")
        context = session.run_command("context cli.lang_pref")
        snapshot = session.run_command("snapshot")
        updated = session.run_command("update fact cli.lang_pref cn 0.95")
        memorized = session.run_command("memorize 记住 cli.topic=memory")
        mem_id = memorized.payload["mem_id"]
        mem_updated = session.run_command(f"update mem {mem_id} 更新后的 CLI memory")
        forgotten = session.run_command(f"forget hard {mem_id} force")
        flushed = session.run_command("flush")
        state = session.run_command("state")

        assert all(
            result.ok
            for result in [
                observed,
                reflected,
                recalled,
                searched,
                context,
                snapshot,
                updated,
                memorized,
                mem_updated,
                forgotten,
                flushed,
                state,
            ]
        )
        assert any(
            fact["fact_key"] == "cli.lang_pref" for fact in recalled.payload["facts"]
        )
        assert searched.payload["episodes"]
        assert "Facts:" in context.payload["context"]
        assert snapshot.payload["l3_facts"] >= 1
        assert updated.payload["action"] in {"replaced", "archived", "merged"}
        assert forgotten.payload["deleted"] == 1
        assert Path(flushed.payload["storage_path"]).exists()
        assert state.payload["exists"] is True
        assert state.payload["l3_facts"] >= 1
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)


def test_memory_cli_view_renders_tree_table_and_json() -> None:
    """Verify view command exposes full memory content in visual formats.

    输入:
        无；测试内部写入一条可反射事实。
    输出:
        None；断言 tree/table/json 均包含结构、元数据和存储内容。
    示例:
        示例输入: session.run_command("view table l3")
        示例输出: payload["rendered"] 包含 l3 semantic facts。
    """
    memory_dir = ".memories/mem-cli-test-view"
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        session = mem_cli.MemoryCliSession(
            config=mem_cli.build_memory_config(memory_dir),
        )
        observed = session.run_command("observe user 记住 cli.view=ok，可视化检查")
        reflected = session.run_command("reflect force")
        tree = session.run_command("view tree all")
        table = session.run_command("view table l3")
        json_view = session.run_command("view json l2")
        invalid = session.run_command("view cards")

        parsed_json_view = json.loads(json_view.payload["rendered"])

        assert observed.ok
        assert reflected.ok
        assert tree.ok
        assert tree.payload["format"] == "tree"
        assert tree.payload["summary"]["l2_records"] >= 1
        assert "l2 episodic memories" in tree.payload["rendered"]
        assert "cli.view" in tree.payload["rendered"]
        assert table.ok
        assert table.payload["layer"] == "l3"
        assert "l3 semantic facts" in table.payload["rendered"]
        assert "fact_key" in table.payload["rendered"]
        assert "l3" in table.payload["records"]
        assert "l2" not in table.payload["records"]
        assert json_view.ok
        assert parsed_json_view["l2"][0]["text"].startswith("记住 cli.view=ok")
        assert invalid.ok is False
        assert "usage: view" in invalid.message
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)


def test_memory_cli_validate_outputs_capability_report() -> None:
    """Verify validate command reports store, retrieve, update, and delete checks.

    输入:
        无；validate 会执行完整能力验证链路。
    输出:
        None；断言报告中每项能力均为 pass。
    示例:
        示例输入: session.run_command("validate cli.validation.test")
        示例输出: payload["summary"]["rating"] == "pass"。
    """
    memory_dir = ".memories/mem-cli-test-validate"
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        session = mem_cli.MemoryCliSession(
            config=mem_cli.build_memory_config(memory_dir),
        )
        result = session.run_command("validate cli.validation.test")
        check_names = {check["name"] for check in result.payload["checks"]}
        delete_check = next(
            check
            for check in result.payload["checks"]
            if check["name"] == "memory_delete"
        )

        assert result.ok
        assert result.payload["summary"]["rating"] == "pass"
        assert result.payload["summary"]["failed"] == 0
        assert result.payload["summary"]["score"] == 1.0
        assert set(result.payload["capabilities"].values()) == {"pass"}
        assert {
            "agents_and_memory_modules_connected",
            "memory_store",
            "memory_reflect",
            "memory_retrieval",
            "memory_update",
            "memory_delete",
            "memory_visualization",
            "memory_persistence",
        } <= check_names
        assert delete_check["details"]["status"] == "deleted"
        assert result.payload["recommendations"] == []
        assert session.run_command("state").payload["exists"] is True
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)


def test_memory_cli_replays_mock_scenario_into_fresh_session() -> None:
    """Verify scenario command replays reusable mock data through L0-L4.

    输入:
        无；通过 scenario 命令回放正常 mock 对话。
    输出:
        None；断言消息、事实、情景记忆和图谱均有结果。
    示例:
        示例输入: session.run_command("scenario product_engineer_memory_flow")
        示例输出: payload["facts"] >= 3。
    """
    memory_dir = ".memories/mem-cli-test-scenario"
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        session = mem_cli.MemoryCliSession(
            config=mem_cli.build_memory_config(memory_dir),
        )
        result = session.run_command("scenario product_engineer_memory_flow")

        assert result.ok
        assert result.payload["messages"] >= 10
        assert result.payload["promoted"] >= 3
        assert result.payload["reflection"]["n_facts"] >= 3
        assert result.payload["facts"] >= 3
        assert result.payload["episodes"] >= 1
        assert result.payload["subgraph_nodes"] >= 1
        assert result.payload["snapshot"]["l4_nodes"] >= 1
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)


def test_memory_cli_main_runs_non_interactive_commands(
    capsys: Any,
) -> None:
    """Verify main supports repeated --command execution without entering REPL.

    输入:
        capsys: pytest 捕获输出 fixture。
    输出:
        None；断言 main 返回 0 且输出包含 recall 结果。
    示例:
        示例输入: mem_cli.main(["--command", "help"])
        示例输出: 0
    """
    memory_dir = ".memories/mem-cli-test-main"
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        exit_code = mem_cli.main(
            [
                "--memory-dir",
                memory_dir,
                "--command",
                "observe user 记住 cli.main=ok",
                "--command",
                "reflect force",
                "--command",
                "recall cli.main 3",
            ]
        )
        output = capsys.readouterr().out
        objects = _read_json_objects(output)

        assert exit_code == 0
        assert [item["command"] for item in objects] == [
            "observe",
            "reflect",
            "recall",
        ]
        assert objects[-1]["payload"]["facts"][0]["fact_key"] == "cli.main"
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)


def test_memory_cli_repl_and_failure_paths_are_reported() -> None:
    """Verify REPL reads commands from a stream and reports failures as JSON.

    输入:
        无；测试内部使用 StringIO 模拟输入输出流。
    输出:
        None；断言错误命令导致非零退出码但不会抛异常。
    示例:
        示例输入: run_repl(session, StringIO("unknown\\nexit\\n"), output)
        示例输出: 1
    """
    memory_dir = ".memories/mem-cli-test-repl"
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        session = mem_cli.MemoryCliSession(
            config=mem_cli.build_memory_config(memory_dir),
        )
        input_stream = io.StringIO("help\nunknown\nexit\n")
        output_stream = io.StringIO()
        exit_code = mem_cli.run_repl(session, input_stream, output_stream)
        objects = _read_json_objects(output_stream.getvalue())

        assert exit_code == 1
        assert objects[0]["ok"] is True
        assert objects[1]["ok"] is False
        assert objects[1]["message"] == (
            "unknown command: unknown. Run `help` for usage."
        )
        assert objects[2]["command"] == "exit"
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)


def test_memory_cli_argument_and_parser_helpers() -> None:
    """Verify small CLI parser helpers cover boundary behavior.

    输入:
        无；直接调用 helper 函数。
    输出:
        None；断言 query/k 拆分、float 判断和 scenario 查询正常。
    示例:
        示例输入: split_query_and_k(["abc", "2"], 8)
        示例输出: ("abc", 2)
    """
    assert mem_cli.split_query_and_k(["abc", "2"], 8) == ("abc", 2)
    assert mem_cli.split_query_and_k(["abc"], 8) == ("abc", 8)
    assert mem_cli.is_float("0.95") is True
    assert mem_cli.is_float("text") is False
    assert mem_cli.find_scenario("product_engineer_memory_flow") is not None
    assert mem_cli.find_scenario("missing-scenario") is None
    args = mem_cli.parse_args(["--command", "help", "--no-repl"])
    assert args.command == ["help"]
    assert args.no_repl is True
