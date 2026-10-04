#!/usr/bin/env python3
"""Interactive command-line Agent built on agent_provider with memory."""

from __future__ import annotations

import argparse
import json
import logging
import shlex
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
SRC_DIR = PROJECT_ROOT / "src"
TESTS_DIR = PROJECT_ROOT / "tests"
for _path in (REPO_ROOT, SRC_DIR, TESTS_DIR):
    _path_text = str(_path)
    if _path_text not in sys.path:
        sys.path.insert(0, _path_text)

from agent_provider import (  # noqa: E402
    ChatMessage,
    LLMProvider,
    ProviderInitError,
    Settings,
    build_llm_provider,
    get_settings,
)

DEFAULT_MEMORY_DIR = ".memories/agent-cli"
DEFAULT_SESSION_ID = "agent-cli-session"
DEFAULT_SYSTEM_PROMPT = (
    "You are a concise CLI assistant. Use the provided conversation memory "
    "when it is relevant, and clearly answer the latest user request."
)
EXIT_COMMANDS = {"exit", "quit", ":q"}
HELP_COMMANDS = {"help", ":help", "/help"}
LOGGER = logging.getLogger("agent_cli")


@dataclass
class AgentCliConfig:
    """Runtime configuration for the CLI Agent.

    Example Input:
        AgentCliConfig(memory_dir=".memories/demo", provider="custom")

    Example Output:
        A config object consumed by MemoryAwareAgent and JsonFileMemoryStore.
    """

    memory_dir: str = DEFAULT_MEMORY_DIR
    session_id: str = DEFAULT_SESSION_ID
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    base_url: Optional[str] = None
    api_mode: Optional[str] = None
    max_history_turns: int = 8
    max_memory_items: int = 20
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    system_prompt: str = DEFAULT_SYSTEM_PROMPT


@dataclass
class ConversationTurn:
    """One persisted user/assistant exchange.

    Example Input:
        ConversationTurn(1, "Hi", "Hello", "2026-01-01T00:00:00+00:00")

    Example Output:
        A serializable turn used by short-term and long-term memory.
    """

    turn_id: int
    user: str
    assistant: str
    created_at: str
    context_memory: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the turn to a JSON-compatible dictionary.

        Example Input:
            ConversationTurn(1, "u", "a", "ts").to_dict()

        Example Output:
            {"turn_id": 1, "user": "u", "assistant": "a", ...}
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationTurn":
        """Build a turn from stored JSON data.

        Example Input:
            ConversationTurn.from_dict({"turn_id": 1, "user": "u"})

        Example Output:
            ConversationTurn(turn_id=1, user="u", assistant="", ...)
        """
        return cls(
            turn_id=int(data.get("turn_id", 0)),
            user=str(data.get("user", "")),
            assistant=str(data.get("assistant", "")),
            created_at=str(data.get("created_at", "")),
            context_memory=list(data.get("context_memory", [])),
        )


@dataclass
class AgentResponse:
    """Structured response returned by the memory-aware Agent.

    Example Input:
        AgentResponse("ok", [], "custom", 1)

    Example Output:
        A response object that can be rendered by the CLI layer.
    """

    answer: str
    context_memory: List[Dict[str, Any]]
    provider: str
    turn_id: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert the response to a JSON-compatible dictionary.

        Example Input:
            AgentResponse("ok", [], "custom", 1).to_dict()

        Example Output:
            {"answer": "ok", "context_memory": [], "provider": "custom", ...}
        """
        return asdict(self)


@dataclass
class CliCommandResult:
    """Structured result returned by one CLI command.

    Example Input:
        CliCommandResult(True, "help", {"commands": []}, "ok")

    Example Output:
        A serializable command result.
    """

    ok: bool
    command: str
    payload: Dict[str, Any]
    message: str = ""
    exit_requested: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert the result to a JSON-compatible dictionary.

        Example Input:
            CliCommandResult(True, "noop", {}).to_dict()

        Example Output:
            {"ok": True, "command": "noop", "message": "", "payload": {}}
        """
        return {
            "ok": self.ok,
            "command": self.command,
            "message": self.message,
            "payload": self.payload,
        }


class MemoryStore(Protocol):
    """Extensible persistence interface for conversation memory.

    Example Input:
        store = JsonFileMemoryStore(".memories/agent-cli")

    Example Output:
        A store implementing load, save, clear, and export operations.
    """

    def load_session(self, session_id: str) -> List[ConversationTurn]:
        """Load all turns for a session.

        Example Input:
            store.load_session("demo")

        Example Output:
            [ConversationTurn(...)]
        """
        ...

    def save_session(
        self,
        session_id: str,
        turns: Sequence[ConversationTurn],
    ) -> Path:
        """Persist all turns for a session.

        Example Input:
            store.save_session("demo", [turn])

        Example Output:
            Path(".memories/agent-cli/demo.json")
        """
        ...

    def clear_session(self, session_id: str) -> bool:
        """Delete stored turns for a session.

        Example Input:
            store.clear_session("demo")

        Example Output:
            True
        """
        ...

    def export_session(
        self,
        session_id: str,
        output_path: Optional[str] = None,
    ) -> Path:
        """Export a session to a JSON file.

        Example Input:
            store.export_session("demo", "export.json")

        Example Output:
            Path("export.json")
        """
        ...


class JsonFileMemoryStore:
    """JSON file-backed memory store for CLI conversations.

    Example Input:
        JsonFileMemoryStore(".memories/agent-cli")

    Example Output:
        A local file store for long-term conversation memory.
    """

    def __init__(self, memory_dir: str) -> None:
        """Initialize the store and create the memory directory.

        Example Input:
            JsonFileMemoryStore(".memories/agent-cli")

        Example Output:
            A store whose base directory exists.
        """
        self.base_dir = Path(memory_dir).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def session_path(self, session_id: str) -> Path:
        """Return the JSON path for a session.

        Example Input:
            store.session_path("demo/session")

        Example Output:
            Path(".memories/agent-cli/demo_session.json")
        """
        return self.base_dir / f"{sanitize_session_id(session_id)}.json"

    def load_session(self, session_id: str) -> List[ConversationTurn]:
        """Load all turns for a session from JSON.

        Example Input:
            store.load_session("demo")

        Example Output:
            [ConversationTurn(turn_id=1, ...)] or [] when absent/corrupt.
        """
        path = self.session_path(session_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("failed to load memory file %s: %s", path, exc)
            return []
        turns = data.get("turns", [])
        if not isinstance(turns, list):
            LOGGER.warning("memory file %s has invalid turns payload", path)
            return []
        return [ConversationTurn.from_dict(item) for item in turns]

    def save_session(
        self,
        session_id: str,
        turns: Sequence[ConversationTurn],
    ) -> Path:
        """Persist all turns for a session.

        Example Input:
            store.save_session("demo", [ConversationTurn(...)])

        Example Output:
            Path to the written session JSON file.
        """
        path = self.session_path(session_id)
        payload = {
            "session_id": session_id,
            "saved_at": utc_now(),
            "turns": [turn.to_dict() for turn in turns],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def clear_session(self, session_id: str) -> bool:
        """Delete a stored session if it exists.

        Example Input:
            store.clear_session("demo")

        Example Output:
            True when a file was removed, otherwise False.
        """
        path = self.session_path(session_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def export_session(
        self,
        session_id: str,
        output_path: Optional[str] = None,
    ) -> Path:
        """Export a session snapshot to a JSON file.

        Example Input:
            store.export_session("demo", "demo-export.json")

        Example Output:
            Path("demo-export.json")
        """
        turns = self.load_session(session_id)
        path = (
            Path(output_path).expanduser()
            if output_path
            else self.base_dir / f"{sanitize_session_id(session_id)}-export.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": session_id,
            "exported_at": utc_now(),
            "turns": [turn.to_dict() for turn in turns],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path


class ShortTermMemory:
    """In-process conversation memory backed by a MemoryStore.

    Example Input:
        ShortTermMemory(store, "demo")

    Example Output:
        A memory object that exposes recent ChatMessage history.
    """

    def __init__(self, store: MemoryStore, session_id: str) -> None:
        """Load existing turns for a session.

        Example Input:
            ShortTermMemory(store, "demo")

        Example Output:
            A memory object initialized with persisted turns.
        """
        self.store = store
        self.session_id = session_id
        self._turns = list(store.load_session(session_id))

    @property
    def turns(self) -> List[ConversationTurn]:
        """Return a copy of all in-memory turns.

        Example Input:
            memory.turns

        Example Output:
            [ConversationTurn(...)]
        """
        return list(self._turns)

    def add_turn(
        self,
        user: str,
        assistant: str,
        context_memory: Sequence[Dict[str, Any]],
    ) -> ConversationTurn:
        """Append a turn and persist the session.

        Example Input:
            memory.add_turn("Hi", "Hello", [])

        Example Output:
            ConversationTurn(turn_id=1, ...)
        """
        turn = ConversationTurn(
            turn_id=len(self._turns) + 1,
            user=user,
            assistant=assistant,
            created_at=utc_now(),
            context_memory=list(context_memory),
        )
        self._turns.append(turn)
        self.store.save_session(self.session_id, self._turns)
        return turn

    def clear(self) -> bool:
        """Clear short-term and persisted memory for the current session.

        Example Input:
            memory.clear()

        Example Output:
            True when persisted data existed, otherwise False.
        """
        self._turns.clear()
        return self.store.clear_session(self.session_id)

    def export(self, output_path: Optional[str] = None) -> Path:
        """Export current memory to a JSON file.

        Example Input:
            memory.export("history.json")

        Example Output:
            Path("history.json")
        """
        self.store.save_session(self.session_id, self._turns)
        return self.store.export_session(self.session_id, output_path)

    def recent_messages(self, max_turns: int) -> List[ChatMessage]:
        """Return recent turns as provider-facing chat messages.

        Example Input:
            memory.recent_messages(2)

        Example Output:
            [ChatMessage(role="user", ...), ChatMessage(role="assistant", ...)]
        """
        if max_turns <= 0:
            return []
        messages: List[ChatMessage] = []
        for turn in self._turns[-max_turns:]:
            messages.append(ChatMessage(role="user", content=turn.user))
            messages.append(ChatMessage(role="assistant", content=turn.assistant))
        return messages

    def memory_references(self, max_items: int) -> List[Dict[str, Any]]:
        """Return compact memory references for the next Agent call.

        Example Input:
            memory.memory_references(1)

        Example Output:
            [{"turn_id": 1, "user": "...", "assistant": "..."}]
        """
        if max_items <= 0:
            return []
        return [
            {
                "turn_id": turn.turn_id,
                "user": turn.user,
                "assistant": turn.assistant,
                "created_at": turn.created_at,
            }
            for turn in self._turns[-max_items:]
        ]

    def long_term_summary(self, max_items: int) -> str:
        """Build a compact textual summary of persisted memory.

        Example Input:
            memory.long_term_summary(2)

        Example Output:
            "1. User: ...\\n   Assistant: ..."
        """
        references = self.memory_references(max_items)
        lines = []
        for item in references:
            lines.append(f"{item['turn_id']}. User: {item['user']}")
            lines.append(f"   Assistant: {item['assistant']}")
        return "\n".join(lines)


class MemoryAwareAgent:
    """Agent logic layer using agent_provider and conversation memory.

    Example Input:
        MemoryAwareAgent(config, provider=provider)

    Example Output:
        An Agent that can answer questions with memory context.
    """

    def __init__(
        self,
        config: AgentCliConfig,
        provider: Optional[LLMProvider] = None,
        store: Optional[MemoryStore] = None,
    ) -> None:
        """Initialize provider, memory store, and short-term memory.

        Example Input:
            MemoryAwareAgent(AgentCliConfig(provider="custom"))

        Example Output:
            A ready-to-use Agent instance.
        """
        self.config = config
        self.provider_name = resolve_provider_name(config)
        self.provider = provider or build_cli_provider(config, self.provider_name)
        self.store = store or JsonFileMemoryStore(config.memory_dir)
        self.memory = ShortTermMemory(self.store, config.session_id)

    def ask(self, user_input: str) -> AgentResponse:
        """Answer one user input and persist the exchange.

        Example Input:
            agent.ask("What did I say earlier?")

        Example Output:
            AgentResponse(answer="...", context_memory=[...], provider="custom")
        """
        question = user_input.strip()
        if not question:
            raise ValueError("user input cannot be empty")
        context_memory = self.memory.memory_references(self.config.max_memory_items)
        messages = self._build_messages(question)
        try:
            answer = self.provider.chat(
                messages,
                **self._generation_kwargs(),
            )
        except Exception as exc:  # noqa: BLE001 - CLI boundary reports provider errors.
            LOGGER.exception("provider chat failed")
            raise RuntimeError(f"LLM provider failed: {exc}") from exc
        turn = self.memory.add_turn(question, answer, context_memory)
        return AgentResponse(
            answer=answer,
            context_memory=context_memory,
            provider=self.provider_name,
            turn_id=turn.turn_id,
        )

    def clear_memory(self) -> bool:
        """Clear current session memory.

        Example Input:
            agent.clear_memory()

        Example Output:
            True when stored memory was removed.
        """
        return self.memory.clear()

    def export_memory(self, output_path: Optional[str] = None) -> Path:
        """Export current session memory.

        Example Input:
            agent.export_memory("history.json")

        Example Output:
            Path("history.json")
        """
        return self.memory.export(output_path)

    def history(self) -> List[ConversationTurn]:
        """Return current session history.

        Example Input:
            agent.history()

        Example Output:
            [ConversationTurn(...)]
        """
        return self.memory.turns

    def _build_messages(self, question: str) -> List[ChatMessage]:
        """Build provider messages from prompt, memory, and latest input.

        Example Input:
            agent._build_messages("Hi")

        Example Output:
            [ChatMessage(role="system", ...), ChatMessage(role="user", ...)]
        """
        messages = [ChatMessage(role="system", content=self.config.system_prompt)]
        summary = self.memory.long_term_summary(self.config.max_memory_items)
        if summary:
            messages.append(
                ChatMessage(
                    role="system",
                    content=(
                        "Long-term conversation memory for this session:\n"
                        f"{summary}"
                    ),
                )
            )
        messages.extend(self.memory.recent_messages(self.config.max_history_turns))
        messages.append(ChatMessage(role="user", content=question))
        return messages

    def _generation_kwargs(self) -> Dict[str, Any]:
        """Return provider generation keyword arguments.

        Example Input:
            agent._generation_kwargs()

        Example Output:
            {"temperature": 0.2, "max_tokens": 500}
        """
        kwargs: Dict[str, Any] = {"temperature": self.config.temperature}
        if self.config.max_tokens is not None:
            kwargs["max_tokens"] = self.config.max_tokens
        return kwargs


class AgentCliSession:
    """Command dispatcher for the interactive Agent CLI.

    Example Input:
        AgentCliSession(agent).run_command("ask hello")

    Example Output:
        CliCommandResult(ok=True, command="ask", ...)
    """

    def __init__(self, agent: MemoryAwareAgent) -> None:
        """Create a CLI session around an Agent.

        Example Input:
            AgentCliSession(agent)

        Example Output:
            A command dispatcher with Agent state.
        """
        self.agent = agent

    def run_command(self, raw_command: str) -> CliCommandResult:
        """Run one command or natural-language user message.

        Example Input:
            session.run_command("ask What is my name?")

        Example Output:
            CliCommandResult(command="ask", ok=True, ...)
        """
        stripped = raw_command.strip()
        if not stripped:
            return CliCommandResult(True, "noop", {}, "empty input")
        lowered = stripped.lower()
        if lowered in EXIT_COMMANDS:
            return CliCommandResult(True, "exit", {}, "bye", exit_requested=True)
        if lowered in HELP_COMMANDS:
            return self._help()
        try:
            parts = shlex.split(stripped)
        except ValueError as exc:
            return CliCommandResult(False, "parse", {}, str(exc))
        if not parts:
            return CliCommandResult(True, "noop", {}, "empty input")
        command = parts[0].lower()
        args = parts[1:]
        try:
            return self._dispatch(command, args, stripped)
        except Exception as exc:  # noqa: BLE001 - command loop must not crash.
            return CliCommandResult(
                False,
                command,
                {"error_type": type(exc).__name__},
                str(exc),
            )

    def _dispatch(
        self,
        command: str,
        args: Sequence[str],
        raw_command: str,
    ) -> CliCommandResult:
        """Dispatch parsed command tokens to Agent operations.

        Example Input:
            session._dispatch("history", [], "history")

        Example Output:
            CliCommandResult(command="history", ok=True, ...)
        """
        if command == "ask":
            return self._ask(" ".join(args))
        if command in {"clear", ":clear", "/clear"}:
            removed = self.agent.clear_memory()
            return CliCommandResult(
                True,
                "clear",
                {"removed_persisted_memory": removed},
                "memory cleared",
            )
        if command in {"history", ":history", "/history"}:
            return self._history()
        if command in {"export", ":export", "/export"}:
            output_path = args[0] if args else None
            return self._export(output_path)
        if command in HELP_COMMANDS:
            return self._help()
        if command in EXIT_COMMANDS:
            return CliCommandResult(True, "exit", {}, "bye", exit_requested=True)
        return self._ask(raw_command)

    def _ask(self, question: str) -> CliCommandResult:
        """Ask the Agent one question.

        Example Input:
            session._ask("hello")

        Example Output:
            CliCommandResult(command="ask", payload={"answer": "..."})
        """
        response = self.agent.ask(question)
        return CliCommandResult(
            True,
            "ask",
            response.to_dict(),
            "answer generated",
        )

    def _history(self) -> CliCommandResult:
        """Return current session history.

        Example Input:
            session._history()

        Example Output:
            CliCommandResult(payload={"turns": [...]})
        """
        turns = [turn.to_dict() for turn in self.agent.history()]
        return CliCommandResult(
            True,
            "history",
            {"turns": turns, "count": len(turns)},
            "history loaded",
        )

    def _export(self, output_path: Optional[str]) -> CliCommandResult:
        """Export current session memory.

        Example Input:
            session._export("history.json")

        Example Output:
            CliCommandResult(payload={"export_path": "history.json"})
        """
        path = self.agent.export_memory(output_path)
        return CliCommandResult(
            True,
            "export",
            {"export_path": str(path), "turns": len(self.agent.history())},
            "memory exported",
        )

    def _help(self) -> CliCommandResult:
        """Return available CLI commands.

        Example Input:
            session._help()

        Example Output:
            CliCommandResult(payload={"commands": [...]})
        """
        commands = [
            "ask <question>",
            "history",
            "clear",
            "export [path]",
            "help",
            "exit",
        ]
        return CliCommandResult(
            True,
            "help",
            {"commands": commands},
            "available commands",
        )


def resolve_provider_name(config: AgentCliConfig) -> str:
    """Resolve the provider name from CLI config or agent_provider settings.

    Example Input:
        resolve_provider_name(AgentCliConfig(provider=None))

    Example Output:
        "custom"
    """
    if config.provider:
        return config.provider
    return get_settings().provider


def build_cli_provider(config: AgentCliConfig, provider_name: str) -> LLMProvider:
    """Build the provider used by the CLI through agent_provider.

    Example Input:
        build_cli_provider(AgentCliConfig(), "custom")

    Example Output:
        AzureOpenAILLMProvider(...)
    """
    return build_llm_provider(build_provider_settings(config, provider_name))


def build_provider_settings(config: AgentCliConfig, provider_name: str) -> Settings:
    """Build agent_provider settings from CLI args and environment.

    Example Input:
        build_provider_settings(AgentCliConfig(provider="custom"), "custom")

    Example Output:
        Settings(provider="custom", ...)
    """
    env = get_settings()
    return Settings(
        provider=provider_name,
        api_key=config.api_key or env.api_key,
        base_url=config.base_url or env.base_url,
        endpoint=config.endpoint or env.endpoint,
        api_version=env.api_version,
        embedding_api_version=env.embedding_api_version,
        llm_model=config.model or env.llm_model,
        embedding_model=env.embedding_model,
        embedding_base_url=env.embedding_base_url,
        embedding_endpoint=env.embedding_endpoint,
        embedding_dim=env.embedding_dim,
        openai_api_mode=config.api_mode or env.openai_api_mode,
        extra_headers=env.extra_headers,
        tracing_disabled=env.tracing_disabled,
    )


def build_agent(
    config: AgentCliConfig,
    provider: Optional[LLMProvider] = None,
    store: Optional[MemoryStore] = None,
) -> MemoryAwareAgent:
    """Build a MemoryAwareAgent with injectable dependencies.

    Example Input:
        build_agent(AgentCliConfig(provider="custom"))

    Example Output:
        MemoryAwareAgent(...)
    """
    return MemoryAwareAgent(config=config, provider=provider, store=store)


def sanitize_session_id(session_id: str) -> str:
    """Convert a session id into a safe file stem.

    Example Input:
        sanitize_session_id("../demo session")

    Example Output:
        "demo_session"
    """
    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in session_id.strip()
    )
    cleaned = cleaned.strip("._")
    return cleaned or "default-session"


def utc_now() -> str:
    """Return the current UTC timestamp in ISO 8601 form.

    Example Input:
        utc_now()

    Example Output:
        "2026-01-01T00:00:00+00:00"
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dump_result(result: CliCommandResult, output_stream: TextIO) -> None:
    """Write one command result as JSON Lines.

    Example Input:
        dump_result(CliCommandResult(True, "help", {}), sys.stdout)

    Example Output:
        stdout receives one JSON object followed by a newline.
    """
    output_stream.write(json.dumps(result.to_dict(), ensure_ascii=False))
    output_stream.write("\n")
    output_stream.flush()


def render_result(result: CliCommandResult) -> str:
    """Render a command result for human-readable CLI output.

    Example Input:
        render_result(CliCommandResult(True, "ask", {"answer": "hi"}))

    Example Output:
        "Agent: hi"
    """
    if not result.ok:
        return f"Error: {result.message}"
    if result.command == "ask":
        return f"Agent: {result.payload['answer']}"
    if result.command == "history":
        return render_history(result.payload["turns"])
    if result.command == "help":
        return "Commands:\n" + "\n".join(
            f"  {command}" for command in result.payload["commands"]
        )
    if result.command == "export":
        return f"Exported memory to {result.payload['export_path']}"
    if result.command == "clear":
        return "Memory cleared."
    if result.command == "exit":
        return "Bye."
    return result.message or result.command


def render_history(turns: Sequence[Dict[str, Any]]) -> str:
    """Render persisted turns as readable text.

    Example Input:
        render_history([{"turn_id": 1, "user": "u", "assistant": "a"}])

    Example Output:
        "History:\\n[1] User: u\\n    Agent: a"
    """
    if not turns:
        return "History is empty."
    lines = ["History:"]
    for turn in turns:
        lines.append(f"[{turn['turn_id']}] User: {turn['user']}")
        lines.append(f"    Agent: {turn['assistant']}")
    return "\n".join(lines)


def run_repl(
    session: AgentCliSession,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    json_output: bool = False,
) -> int:
    """Run the interactive Agent command loop.

    Example Input:
        run_repl(session, StringIO("help\\nexit\\n"), output)

    Example Output:
        0
    """
    had_error = False
    interactive = input_stream.isatty()
    while True:
        if interactive:
            output_stream.write("agent> ")
            output_stream.flush()
        line = input_stream.readline()
        if not line:
            break
        result = session.run_command(line)
        had_error = had_error or not result.ok
        write_result(result, output_stream, json_output)
        if result.exit_requested:
            break
    return 1 if had_error else 0


def run_scripted_commands(
    session: AgentCliSession,
    commands: Iterable[str],
    output_stream: TextIO,
    json_output: bool = False,
) -> int:
    """Run a finite command list without entering the REPL.

    Example Input:
        run_scripted_commands(session, ["ask hi"], output)

    Example Output:
        0
    """
    had_error = False
    for command in commands:
        result = session.run_command(command)
        had_error = had_error or not result.ok
        write_result(result, output_stream, json_output)
        if result.exit_requested:
            break
    return 1 if had_error else 0


def write_result(
    result: CliCommandResult,
    output_stream: TextIO,
    json_output: bool,
) -> None:
    """Write a CLI result as JSON or human-readable text.

    Example Input:
        write_result(result, sys.stdout, json_output=True)

    Example Output:
        The result is written to the output stream.
    """
    if json_output:
        dump_result(result, output_stream)
        return
    output_stream.write(render_result(result))
    output_stream.write("\n")
    output_stream.flush()


def provider_init_hint(error: ProviderInitError) -> str:
    """Return the actionable hint for a provider initialization failure.

    Example Input:
        error = ProviderInitError("OpenAI provider requires the openai package")
        provider_init_hint(error)

    Example Output:
        "Install the real provider dependency in this environment: ..."
    """
    message = str(error).lower()
    if "openai-agents" in message:
        return (
            "Install the real provider dependencies in this environment: "
            "python3 -m pip install openai openai-agents"
        )
    if "openai package" in message:
        return (
            "Install the real provider dependency in this environment: "
            "python3 -m pip install openai"
        )
    return (
        "Check agent_provider environment variables such as OPENAI_API_KEY, "
        "OPENAI_ENDPOINT, RAG_OPENAI_ENDPOINT, or OPENAI_BASE_URL."
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse process command-line arguments.

    Example Input:
        parse_args(["--message", "hello"])

    Example Output:
        Namespace(message=["hello"], ...)
    """
    parser = argparse.ArgumentParser(
        description="Memory-aware CLI Agent powered by agent_provider.",
    )
    parser.add_argument("--memory-dir", default=DEFAULT_MEMORY_DIR)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument(
        "--provider",
        choices=["custom", "openai"],
        help="Provider backend. Defaults to agent_provider environment settings.",
    )
    parser.add_argument("--model", help="LLM model or deployment name.")
    parser.add_argument("--api-key", help="API key override.")
    parser.add_argument("--endpoint", help="Provider endpoint override.")
    parser.add_argument("--base-url", help="OpenAI-compatible base URL override.")
    parser.add_argument(
        "--api-mode",
        choices=["auto", "chat", "responses"],
        help="OpenAI API mode override.",
    )
    parser.add_argument("--max-history-turns", type=int, default=8)
    parser.add_argument("--max-memory-items", type=int, default=20)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--json", action="store_true", help="Print JSON Lines.")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--message",
        action="append",
        default=[],
        help="Ask one message non-interactively; can be repeated.",
    )
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        help="Run one CLI command non-interactively; can be repeated.",
    )
    parser.add_argument("--no-repl", action="store_true")
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> AgentCliConfig:
    """Build AgentCliConfig from parsed argparse values.

    Example Input:
        config_from_args(parse_args(["--session-id", "demo"]))

    Example Output:
        AgentCliConfig(session_id="demo", ...)
    """
    return AgentCliConfig(
        memory_dir=args.memory_dir,
        session_id=args.session_id,
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        endpoint=args.endpoint,
        base_url=args.base_url,
        api_mode=args.api_mode,
        max_history_turns=args.max_history_turns,
        max_memory_items=args.max_memory_items,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )


def configure_logging(verbose: bool) -> None:
    """Configure process logging for the CLI.

    Example Input:
        configure_logging(verbose=True)

    Example Output:
        Logging is configured at DEBUG level.
    """
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s:%(name)s:%(message)s")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI Agent entrypoint.

    Example Input:
        main(["--message", "hello", "--json"])

    Example Output:
        0
    """
    args = parse_args(argv)
    configure_logging(args.verbose)
    commands = [f"ask {shlex.quote(message)}" for message in args.message]
    commands.extend(args.command)
    if not commands and args.no_repl:
        return 0
    try:
        agent = build_agent(config_from_args(args))
    except ProviderInitError as exc:
        sys.stderr.write(f"Provider initialization failed: {exc}\n")
        sys.stderr.write(f"{provider_init_hint(exc)}\n")
        return 1
    session = AgentCliSession(agent)
    if commands:
        return run_scripted_commands(session, commands, sys.stdout, args.json)
    return run_repl(session, json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
