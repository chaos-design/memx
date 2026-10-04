"""Tests for the memory-aware agent_provider CLI Agent."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

import agent_cli
import pytest


class RecordingProvider(agent_cli.LLMProvider):
    """Test double that records provider messages and returns fixed answers.

    Example Input:
        RecordingProvider(["ok"]).chat([agent_cli.ChatMessage("user", "hi")])

    Example Output:
        "ok"
    """

    def __init__(self, responses: Sequence[str]) -> None:
        """Initialize fixed responses and call storage.

        Example Input:
            RecordingProvider(["first", "second"])

        Example Output:
            A provider whose calls list starts empty.
        """
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def chat(
        self,
        messages: Sequence[agent_cli.ChatMessage],
        **kwargs: object,
    ) -> str:
        """Record one chat request and return the next configured response.

        Example Input:
            provider.chat([agent_cli.ChatMessage(role="user", content="hi")])

        Example Output:
            "configured response"
        """
        self.calls.append({"messages": list(messages), "kwargs": dict(kwargs)})
        if self.responses:
            return self.responses.pop(0)
        latest = next(
            (
                message.content
                for message in reversed(messages)
                if message.role == "user"
            ),
            "",
        )
        return f"echo:{latest}"


class FailingProvider(agent_cli.LLMProvider):
    """Test double that raises from chat.

    Example Input:
        FailingProvider(RuntimeError("bad")).chat([])

    Example Output:
        Raises RuntimeError("bad").
    """

    def __init__(self, error: Exception) -> None:
        """Initialize the provider with the error to raise.

        Example Input:
            FailingProvider(ValueError("network"))

        Example Output:
            A provider that raises ValueError from chat.
        """
        self.error = error

    def chat(
        self,
        messages: Sequence[agent_cli.ChatMessage],
        **kwargs: object,
    ) -> str:
        """Raise the configured error.

        Example Input:
            provider.chat([agent_cli.ChatMessage(role="user", content="hi")])

        Example Output:
            Raises the configured exception.
        """
        raise self.error


def _make_agent(
    tmp_path: Path,
    provider: agent_cli.LLMProvider,
    session_id: str = "test-session",
) -> agent_cli.MemoryAwareAgent:
    """Build an Agent with a temp JSON store and injected provider.

    Example Input:
        _make_agent(tmp_path, RecordingProvider(["ok"]))

    Example Output:
        MemoryAwareAgent(...)
    """
    config = agent_cli.AgentCliConfig(
        memory_dir=str(tmp_path / "memory"),
        session_id=session_id,
        provider="custom",
        max_history_turns=4,
        max_memory_items=10,
        temperature=0.1,
        max_tokens=128,
    )
    return agent_cli.MemoryAwareAgent(config=config, provider=provider)


def _read_json_lines(text: str) -> List[Dict[str, Any]]:
    """Parse JSON Lines emitted by CLI helpers.

    Example Input:
        _read_json_lines('{"ok": true}\\n')

    Example Output:
        [{"ok": True}]
    """
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_agent_uses_short_term_history_and_persisted_memory(
    tmp_path: Path,
) -> None:
    """Verify Agent replies include current and persisted context.

    Example Input:
        agent.ask("我的名字是 Alice")

    Example Output:
        The next provider call contains Alice in memory context.
    """
    provider = RecordingProvider(["已记住 Alice", "你叫 Alice"])
    agent = _make_agent(tmp_path, provider)

    first = agent.ask("我的名字是 Alice")
    second = agent.ask("我叫什么？")

    assert first.turn_id == 1
    assert first.context_memory == []
    assert second.turn_id == 2
    assert second.context_memory[0]["user"] == "我的名字是 Alice"
    assert provider.calls[1]["kwargs"] == {"temperature": 0.1, "max_tokens": 128}
    second_messages = provider.calls[1]["messages"]
    assert any("Alice" in message.content for message in second_messages)
    assert any(
        message.role == "assistant" and message.content == "已记住 Alice"
        for message in second_messages
    )

    reloaded_provider = RecordingProvider(["继续使用持久化记忆"])
    reloaded = _make_agent(tmp_path, reloaded_provider)
    reloaded.ask("继续")
    reloaded_messages = reloaded_provider.calls[0]["messages"]

    assert any(
        "Long-term conversation memory" in item.content
        for item in reloaded_messages
    )
    assert any("我的名字是 Alice" in item.content for item in reloaded_messages)


def test_json_memory_store_exports_clears_and_handles_invalid_json(
    tmp_path: Path,
) -> None:
    """Verify JSON store persistence, export, clear, and corrupt-file behavior.

    Example Input:
        store.export_session("session", "export.json")

    Example Output:
        Exported JSON contains the saved turn.
    """
    store = agent_cli.JsonFileMemoryStore(str(tmp_path / "memory"))
    turn = agent_cli.ConversationTurn(
        turn_id=1,
        user="u",
        assistant="a",
        created_at="2026-01-01T00:00:00+00:00",
    )

    written_path = store.save_session("../bad/session", [turn])
    loaded = store.load_session("../bad/session")
    export_path = store.export_session(
        "../bad/session",
        str(tmp_path / "exports" / "history.json"),
    )
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    removed = store.clear_session("../bad/session")

    assert written_path.name == "bad_session.json"
    assert loaded[0].user == "u"
    assert exported["turns"][0]["assistant"] == "a"
    assert removed is True
    assert store.clear_session("../bad/session") is False
    assert store.load_session("../bad/session") == []
    assert agent_cli.sanitize_session_id(" ../x y ") == "x_y"

    broken_path = store.session_path("broken")
    broken_path.write_text("{not-json", encoding="utf-8")
    invalid_path = store.session_path("invalid")
    invalid_path.write_text('{"turns": {}}', encoding="utf-8")

    assert store.load_session("broken") == []
    assert store.load_session("invalid") == []


def test_cli_session_commands_cover_help_history_export_clear_and_exit(
    tmp_path: Path,
) -> None:
    """Verify command dispatcher covers normal CLI memory operations.

    Example Input:
        session.run_command("ask hello")

    Example Output:
        result.payload["answer"] == "hi"
    """
    provider = RecordingProvider(["你好"])
    session = agent_cli.AgentCliSession(_make_agent(tmp_path, provider))
    export_path = tmp_path / "history.json"

    help_result = session.run_command("help")
    ask_result = session.run_command("ask hello")
    natural_result = session.run_command("继续回答")
    history_result = session.run_command("history")
    rendered_history = agent_cli.render_result(history_result)
    export_result = session.run_command(f"export {export_path}")
    clear_result = session.run_command("clear")
    empty_history = session.run_command("history")
    exit_result = session.run_command("exit")

    assert help_result.ok
    assert "ask <question>" in help_result.payload["commands"]
    assert ask_result.ok
    assert ask_result.payload["answer"] == "你好"
    assert agent_cli.render_result(ask_result) == "Agent: 你好"
    assert natural_result.ok
    assert natural_result.payload["answer"] == "echo:继续回答"
    assert history_result.payload["count"] == 2
    assert "History:" in rendered_history
    assert export_result.payload["export_path"] == str(export_path)
    assert export_path.exists()
    assert clear_result.payload["removed_persisted_memory"] is True
    assert empty_history.payload["count"] == 0
    assert exit_result.exit_requested is True
    assert agent_cli.render_result(empty_history) == "History is empty."


def test_cli_reports_parse_and_provider_errors_without_crashing(
    tmp_path: Path,
) -> None:
    """Verify parser and provider failures are returned as command results.

    Example Input:
        session.run_command('ask "unterminated')

    Example Output:
        CliCommandResult(ok=False, command="parse", ...)
    """
    session = agent_cli.AgentCliSession(
        _make_agent(tmp_path, FailingProvider(ValueError("network down")))
    )

    noop = session.run_command("   ")
    parse_error = session.run_command('ask "unterminated')
    provider_error = session.run_command("ask hello")
    help_result = session.run_command("/help")

    assert noop.ok
    assert noop.command == "noop"
    assert parse_error.ok is False
    assert parse_error.command == "parse"
    assert provider_error.ok is False
    assert provider_error.command == "ask"
    assert provider_error.payload["error_type"] == "RuntimeError"
    assert "LLM provider failed: network down" in provider_error.message
    assert agent_cli.render_result(provider_error).startswith("Error:")
    assert help_result.ok


def test_repl_and_scripted_commands_render_human_and_json_outputs(
    tmp_path: Path,
) -> None:
    """Verify REPL and scripted execution modes.

    Example Input:
        run_scripted_commands(session, ["ask hi"], output, json_output=True)

    Example Output:
        JSON output contains an ask command result.
    """
    scripted_provider = RecordingProvider(["scripted"])
    scripted_session = agent_cli.AgentCliSession(
        _make_agent(tmp_path, scripted_provider, session_id="scripted")
    )
    json_output = io.StringIO()
    json_exit_code = agent_cli.run_scripted_commands(
        scripted_session,
        ["ask hi", "history", "exit"],
        json_output,
        json_output=True,
    )
    objects = _read_json_lines(json_output.getvalue())

    repl_provider = RecordingProvider(["repl"])
    repl_session = agent_cli.AgentCliSession(
        _make_agent(tmp_path, repl_provider, session_id="repl")
    )
    repl_output = io.StringIO()
    repl_exit_code = agent_cli.run_repl(
        repl_session,
        io.StringIO("ask hello\nhistory\nexit\n"),
        repl_output,
    )

    assert json_exit_code == 0
    assert [item["command"] for item in objects] == ["ask", "history", "exit"]
    assert objects[0]["payload"]["answer"] == "scripted"
    assert repl_exit_code == 0
    assert "Agent: repl" in repl_output.getvalue()
    assert "History:" in repl_output.getvalue()
    assert "Bye." in repl_output.getvalue()


def test_main_builds_real_provider_settings_from_cli_args(
    tmp_path: Path,
    capsys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify main wires argparse config into agent_provider settings.

    Example Input:
        main(["--provider", "custom", "--message", "hi", "--json"])

    Example Output:
        exit code 0 and JSON answer output.
    """
    built_settings: List[agent_cli.Settings] = []

    def fake_build_llm_provider(settings: agent_cli.Settings) -> agent_cli.LLMProvider:
        """Capture settings and return a deterministic provider.

        Example Input:
            fake_build_llm_provider(Settings(provider="custom"))

        Example Output:
            RecordingProvider(["main-answer"])
        """
        built_settings.append(settings)
        return RecordingProvider(["main-answer"])

    monkeypatch.setattr(agent_cli, "build_llm_provider", fake_build_llm_provider)
    exit_code = agent_cli.main(
        [
            "--memory-dir",
            str(tmp_path / "main-memory"),
            "--session-id",
            "main",
            "--provider",
            "custom",
            "--model",
            "model-x",
            "--max-tokens",
            "77",
            "--message",
            'hi "there"',
            "--json",
        ]
    )
    output = capsys.readouterr().out
    objects = _read_json_lines(output)

    assert exit_code == 0
    assert built_settings[0].provider == "custom"
    assert built_settings[0].llm_model == "model-x"
    assert objects[0]["payload"]["answer"] == "main-answer"
    assert agent_cli.parse_args(["--no-repl"]).no_repl is True


def test_main_defaults_to_agent_provider_settings(
    tmp_path: Path,
    capsys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify default CLI provider settings are loaded from agent_provider.

    Example Input:
        main(["--message", "hello", "--json"])

    Example Output:
        exit code 0 and JSON output from the configured provider.
    """
    built_settings: List[agent_cli.Settings] = []

    def fake_get_settings() -> agent_cli.Settings:
        """Return deterministic agent_provider settings for the default path.

        Example Input:
            fake_get_settings()

        Example Output:
            Settings(provider="openai", api_key="sk-test")
        """
        return agent_cli.Settings(
            provider="openai",
            api_key="sk-test",
            llm_model="env-model",
        )

    def fake_build_llm_provider(settings: agent_cli.Settings) -> agent_cli.LLMProvider:
        """Capture settings and return a deterministic provider.

        Example Input:
            fake_build_llm_provider(Settings(provider="openai"))

        Example Output:
            RecordingProvider(["agent-provider hello"])
        """
        built_settings.append(settings)
        return RecordingProvider(["agent-provider hello"])

    monkeypatch.setattr(agent_cli, "get_settings", fake_get_settings)
    monkeypatch.setattr(agent_cli, "build_llm_provider", fake_build_llm_provider)

    exit_code = agent_cli.main(
        [
            "--memory-dir",
            str(tmp_path / "provider-memory"),
            "--session-id",
            "provider-default",
            "--message",
            "hello",
            "--json",
        ]
    )
    output = capsys.readouterr().out
    objects = _read_json_lines(output)

    assert exit_code == 0
    assert built_settings[0].provider == "openai"
    assert built_settings[0].api_key == "sk-test"
    assert built_settings[0].llm_model == "env-model"
    assert objects[0]["payload"]["provider"] == "openai"
    assert objects[0]["payload"]["answer"] == "agent-provider hello"


def test_main_no_repl_exits_without_building_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify --no-repl with no commands exits without provider initialization.

    Example Input:
        main(["--no-repl"])

    Example Output:
        0
    """

    def fail_build_agent(
        config: agent_cli.AgentCliConfig,
    ) -> agent_cli.MemoryAwareAgent:
        """Fail if main initializes the Agent unnecessarily.

        Example Input:
            fail_build_agent(AgentCliConfig())

        Example Output:
            Raises AssertionError.
        """
        raise AssertionError("provider should not be initialized")

    monkeypatch.setattr(agent_cli, "build_agent", fail_build_agent)

    assert agent_cli.main(["--no-repl"]) == 0


def test_main_reports_provider_init_error_without_traceback(
    capsys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify missing real provider dependencies produce a concise CLI error.

    Example Input:
        main(["--message", "hello"])

    Example Output:
        exit code 1 and stderr containing an install hint.
    """

    def fail_build_agent(
        config: agent_cli.AgentCliConfig,
    ) -> agent_cli.MemoryAwareAgent:
        """Raise the provider initialization error seen in a fresh environment.

        Example Input:
            fail_build_agent(AgentCliConfig())

        Example Output:
            Raises ProviderInitError.
        """
        raise agent_cli.ProviderInitError(
            "OpenAI provider requires the openai package"
        )

    monkeypatch.setattr(agent_cli, "build_agent", fail_build_agent)

    exit_code = agent_cli.main(["--message", "hello"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert (
        "Provider initialization failed: OpenAI provider requires the openai package"
        in captured.err
    )
    assert "python3 -m pip install openai" in captured.err


def test_provider_init_hint_distinguishes_dependency_and_config_errors() -> None:
    """Verify provider initialization hints match the failure category.

    Example Input:
        provider_init_hint(ProviderInitError("Custom provider requires OPENAI_API_KEY"))

    Example Output:
        A configuration hint, not an SDK installation hint.
    """
    dependency_hint = agent_cli.provider_init_hint(
        agent_cli.ProviderInitError("OpenAI provider requires the openai package")
    )
    agents_hint = agent_cli.provider_init_hint(
        agent_cli.ProviderInitError(
            "Custom provider requires openai and openai-agents packages"
        )
    )
    config_hint = agent_cli.provider_init_hint(
        agent_cli.ProviderInitError("Custom provider requires OPENAI_API_KEY")
    )

    assert "python3 -m pip install openai" in dependency_hint
    assert "python3 -m pip install openai openai-agents" in agents_hint
    assert "OPENAI_API_KEY" in config_hint
    assert "pip install" not in config_hint
