"""Tests for message ingestion conversion and CLI storage."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

import pytest
from mem import cli
from mem.cli.message_ingest import format_messages, parse_messages
from mem.cli.result import CliError


def _read_json_object(text: str) -> Dict[str, Any]:
    """Parse one JSON object from captured CLI output.

    Example Input:
        _read_json_object('{"ok": true}')
    Example Output:
        {"ok": True}
    """
    return json.loads(text)


def _run_cli(argv: List[str], capsys: Any) -> Dict[str, Any]:
    """Run mem.cli.main and return the parsed JSON payload.

    Example Input:
        _run_cli(["snapshot"], capsys)
    Example Output:
        {"ok": True, "command": "snapshot", ...}
    """
    exit_code = cli.main(argv)
    captured = capsys.readouterr()
    output = captured.out if exit_code == 0 else captured.err
    parsed = _read_json_object(output)
    assert exit_code == (0 if parsed["ok"] else 1)
    return parsed


def _base_args(memory_dir: str, scope_id: str) -> List[str]:
    """Return shared CLI arguments for isolated ingestion tests.

    Example Input:
        _base_args(".memories/test", "scope")
    Example Output:
        ["--memory-dir", ".memories/test", "--scope-id", "scope", ...]
    """
    return [
        "--memory-dir",
        memory_dir,
        "--scope-id",
        scope_id,
        "--session-id",
        "session-ingest",
    ]


def test_parse_messages_supports_text_json_metadata_and_jsonl() -> None:
    """Verify supported input formats become normalized memories.

    Example Input:
        parse_messages("assistant: ok", input_format="text")
    Example Output:
        ParsedMessage(role="assistant", content="ok")
    """
    text_messages = parse_messages(
        "assistant: acknowledged\nplain message",
        input_format="text",
        default_role="user",
        source="stdin",
    )
    json_messages = parse_messages(
        (
            '[{"role":"tool","text":"job done","ts":12,'
            '"metadata":{"run_id":"r1"},"channel":"cli"}]'
        ),
        input_format="json",
        default_role="user",
        source="messages.json",
    )
    jsonl_messages = parse_messages(
        '{"content":"first"}\n{"role":"system","message":"second"}\n',
        input_format="jsonl",
        default_role="assistant",
        source="messages.jsonl",
    )
    converted = [
        message.to_memory_dict("session-a", "scope-a")
        for message in jsonl_messages
    ]
    rendered = format_messages(converted, output_format="jsonl")

    assert text_messages[0].role == "assistant"
    assert text_messages[1].role == "user"
    assert json_messages[0].role == "tool"
    assert json_messages[0].ts == 12.0
    assert json_messages[0].metadata == {"run_id": "r1", "channel": "cli"}
    assert jsonl_messages[0].role == "assistant"
    assert jsonl_messages[1].role == "system"
    assert json.loads(rendered.splitlines()[0])["source"] == "messages.jsonl:1"


@pytest.mark.parametrize(
    "raw_text, input_format, expected",
    [
        pytest.param("", "text", "message content", id="empty_text"),
        pytest.param('{"role":"unknown","content":"x"}', "json", "role", id="bad_role"),
        pytest.param('{"role":"user"}', "json", "content", id="missing_content"),
        pytest.param('{"content":"x","ts":true}', "json", "ts", id="bad_ts"),
        pytest.param(
            '{"content":"x","metadata":[]}',
            "json",
            "metadata",
            id="bad_meta",
        ),
    ],
)
def test_parse_messages_rejects_invalid_input(
    raw_text: str,
    input_format: str,
    expected: str,
) -> None:
    """Verify invalid or boundary input is reported as CliError.

    Example Input:
        parse_messages("", input_format="text")
    Example Output:
        CliError is raised.
    """
    with pytest.raises(CliError, match=expected):
        parse_messages(raw_text, input_format=input_format)


def test_ingest_stdin_observe_persists_messages(
    capsys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify stdin ingestion stores messages through the observe path.

    Example Input:
        printf '记住 ingest.lang=zh' | mem ingest
    Example Output:
        CLI reports count=2 and persisted state contains L2 memory.
    """
    memory_dir = ".memories/mem-ingest-stdin-test"
    scope_id = "mem-ingest-stdin"
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO("记住 ingest.lang_pref=zh\nassistant: 已记录\n"),
        )
        args = _base_args(memory_dir, scope_id)
        ingested = _run_cli(args + ["ingest", "--input-format", "text"], capsys)
        state = _run_cli(args + ["state"], capsys)

        assert ingested["ok"] is True
        assert ingested["payload"]["count"] == 2
        assert ingested["payload"]["stored"] == 2
        assert ingested["payload"]["store_as"] == "observe"
        assert ingested["payload"]["store_results"][0]["mem_id"]
        assert ingested["payload"]["memories"][1]["role"] == "assistant"
        assert state["payload"]["exists"] is True
        assert state["payload"]["l0_sessions"] == 1
        assert state["payload"]["l2_records"] >= 1
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)


def test_ingest_jsonl_file_memorize_writes_output_file(
    capsys: Any,
    tmp_path: Path,
) -> None:
    """Verify file ingestion can write converted memories and L2 records.

    Example Input:
        mem ingest --input messages.jsonl --store-as memorize --output converted.jsonl
    Example Output:
        The output JSONL file exists and state contains two L2 records.
    """
    memory_dir = ".memories/mem-ingest-file-test"
    scope_id = "mem-ingest-file"
    input_path = tmp_path / "messages.jsonl"
    output_path = tmp_path / "converted.jsonl"
    input_path.write_text(
        '{"role":"user","content":"记住 batch.one=1"}\n'
        '{"role":"assistant","message":"batch response"}\n',
        encoding="utf-8",
    )
    shutil.rmtree(Path(memory_dir), ignore_errors=True)
    try:
        args = _base_args(memory_dir, scope_id)
        ingested = _run_cli(
            args
            + [
                "ingest",
                "--input",
                str(input_path),
                "--input-format",
                "jsonl",
                "--store-as",
                "memorize",
                "--importance",
                "7",
                "--output",
                str(output_path),
                "--output-format",
                "jsonl",
            ],
            capsys,
        )
        state = _run_cli(args + ["state"], capsys)
        lines = output_path.read_text(encoding="utf-8").splitlines()

        assert ingested["payload"]["count"] == 2
        assert ingested["payload"]["stored"] == 2
        assert ingested["payload"]["output_path"] == str(output_path)
        assert "memories" not in ingested["payload"]
        assert len(lines) == 2
        assert json.loads(lines[0])["scope_id"] == scope_id
        assert state["payload"]["l2_records"] == 2
    finally:
        shutil.rmtree(Path(memory_dir), ignore_errors=True)


def test_ingest_missing_file_reports_cli_error(capsys: Any) -> None:
    """Verify missing input files produce structured CLI errors.

    Example Input:
        mem ingest --input missing.jsonl
    Example Output:
        {"ok": false, "payload": {"error_type": "CliError"}}
    """
    failed = _run_cli(
        _base_args(".memories/mem-ingest-missing-test", "mem-ingest-missing")
        + ["ingest", "--input", "missing.jsonl"],
        capsys,
    )

    assert failed["ok"] is False
    assert failed["payload"]["error_type"] == "CliError"
    assert "input file does not exist" in failed["message"]
