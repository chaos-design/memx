#!/usr/bin/env python3
"""Interactive CLI for debugging the full MemX capability surface."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
TESTS_DIR = PROJECT_ROOT / "tests"
for _path in (SRC_DIR, TESTS_DIR):
    _path_text = str(_path)
    if _path_text not in sys.path:
        sys.path.insert(0, _path_text)

from mem import AgentMemory, MemoryConfig  # noqa: E402
from mock_conversations import ALL_MOCK_SCENARIO_GROUPS  # noqa: E402

DEFAULT_MEMORY_DIR = ".memories/mem-cli"
DEFAULT_SESSION_ID = "cli-session"
DEFAULT_SCOPE_ID = "cli-scope"
VIEW_FORMATS = {"json", "table", "tree"}
VIEW_LAYERS = {"all", "l0", "l1", "l2", "l3", "l4", "inbox"}


@dataclass
class CliCommandResult:
    """Structured result returned by a CLI command.

    输入:
        ok: 命令是否成功。
        command: 命令名称。
        payload: JSON-compatible 命令结果。
        message: 可读摘要。
        exit_requested: 是否请求退出 REPL。
    输出:
        CliCommandResult: 可序列化的 CLI 命令结果。
    示例:
        示例输入: CliCommandResult(True, "help", {"commands": []}, "ok")
        示例输出: result.to_dict()["ok"] == True
    """

    ok: bool
    command: str
    payload: Dict[str, Any]
    message: str = ""
    exit_requested: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert the result into a JSON-compatible dictionary.

        输入:
            self: CLI 命令结果。
        输出:
            dict: 可通过 json.dumps 序列化的结果。
        示例:
            示例输入: CliCommandResult(True, "help", {}).to_dict()
            示例输出: {"ok": True, "command": "help", ...}
        """
        return {
            "ok": self.ok,
            "command": self.command,
            "message": self.message,
            "payload": self.payload,
        }


class MemoryCliSession:
    """Stateful interactive shell session around AgentMemory."""

    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        session_id: str = DEFAULT_SESSION_ID,
        scope_id: str = DEFAULT_SCOPE_ID,
    ) -> None:
        """Create an interactive memory debugging session.

        输入:
            config: MemoryConfig 配置；None 使用 CLI 默认配置。
            session_id: 默认会话 ID。
            scope_id: 默认作用域 ID。
        输出:
            None；初始化 AgentMemory 实例。
        示例:
            示例输入: MemoryCliSession(MemoryConfig(memory_dir=".memories/demo"))
            示例输出: 可执行 observe/recall 等命令的 session。
        """
        self.config = config or build_memory_config(DEFAULT_MEMORY_DIR)
        self.session_id = session_id
        self.scope_id = scope_id
        self.memory = AgentMemory(self.config)

    def run_command(self, raw_command: str) -> CliCommandResult:
        """Parse and execute one interactive command line.

        输入:
            raw_command: 用户输入的一行命令。
        输出:
            CliCommandResult: 命令执行结果；异常会被转为失败结果。
        示例:
            示例输入: session.run_command("observe user 记住 cli.lang=zh")
            示例输出: CliCommandResult(ok=True, command="observe", ...)
        """
        stripped = raw_command.strip()
        if not stripped:
            return CliCommandResult(True, "noop", {}, "empty command")
        try:
            parts = shlex.split(stripped)
        except ValueError as exc:
            return CliCommandResult(False, "parse", {}, str(exc))
        if not parts:
            return CliCommandResult(True, "noop", {}, "empty command")
        command = parts[0].lower()
        args = parts[1:]
        try:
            return self._dispatch(command, args)
        except Exception as exc:  # noqa: BLE001 - CLI must report errors, not crash.
            return CliCommandResult(
                False,
                command,
                {"error_type": type(exc).__name__},
                str(exc),
            )

    def _dispatch(self, command: str, args: Sequence[str]) -> CliCommandResult:
        """Dispatch parsed command tokens to the matching operation.

        输入:
            command: 命令名称。
            args: 命令参数列表。
        输出:
            CliCommandResult: 命令执行结果。
        示例:
            示例输入: session._dispatch("help", [])
            示例输出: CliCommandResult(ok=True, command="help", ...)
        """
        if command in {"exit", "quit"}:
            return CliCommandResult(True, command, {}, "bye", exit_requested=True)
        if command == "help":
            return self._help()
        if command in {"list", "scenarios"}:
            return self._list_scenarios()
        if command == "scenario":
            return self._run_named_scenario(args)
        if command == "observe":
            return self._observe(args)
        if command == "memorize":
            return self._memorize(args)
        if command == "reflect":
            return self._reflect(args)
        if command == "recall":
            return self._recall(args, include_archived=True)
        if command == "search":
            return self._recall(args, include_archived=False)
        if command == "context":
            return self._context(args)
        if command == "snapshot":
            return self._snapshot()
        if command == "view":
            return self._view(args)
        if command == "validate":
            return self._validate(args)
        if command == "forget":
            return self._forget(args)
        if command == "update":
            return self._update(args)
        if command == "flush":
            return self._flush()
        if command == "state":
            return self._state()
        msg = f"unknown command: {command}. Run `help` for usage."
        return CliCommandResult(False, command, {}, msg)

    def _help(self) -> CliCommandResult:
        """Return command usage for the interactive shell.

        输入:
            self: 当前 CLI session。
        输出:
            CliCommandResult: 包含 commands 用法清单。
        示例:
            示例输入: session._help()
            示例输出: payload["commands"] 包含 observe。
        """
        commands = [
            "observe <role> <content>",
            "memorize <text>",
            "reflect [force|auto]",
            "recall <query> [k]",
            "search <query> [k]",
            "context [query]",
            "snapshot",
            "view [tree|table|json] [all|l0|l1|l2|l3|l4|inbox]",
            "validate [fact_key]",
            "forget decay|expire|hard [mem_id] [force]",
            "update fact <fact_key> <value> [confidence]",
            "update mem <mem_id> <text>",
            "flush",
            "state",
            "list",
            "scenario <scenario_name>",
            "help",
            "exit",
        ]
        return CliCommandResult(
            True,
            "help",
            {"commands": commands},
            "available commands",
        )

    def _list_scenarios(self) -> CliCommandResult:
        """List reusable mock scenarios available to the CLI.

        输入:
            self: 当前 CLI session。
        输出:
            CliCommandResult: 按分组列出的 scenario 名称。
        示例:
            示例输入: session._list_scenarios()
            示例输出: payload["normal"] 包含 product_engineer_memory_flow。
        """
        scenarios: Dict[str, List[str]] = {}
        for group, items in ALL_MOCK_SCENARIO_GROUPS.items():
            runnable = [
                scenario["name"] for scenario in items if is_replay_scenario(scenario)
            ]
            if runnable:
                scenarios[group] = runnable
        return CliCommandResult(True, "list", scenarios, "available scenarios")

    def _run_named_scenario(self, args: Sequence[str]) -> CliCommandResult:
        """Replay one named mock scenario into a fresh memory session.

        输入:
            args: 第一个参数为 mock scenario 名称。
        输出:
            CliCommandResult: observe/reflect/recall/context/snapshot 摘要。
        示例:
            示例输入: session._run_named_scenario(["product_engineer_memory_flow"])
            示例输出: payload["facts"] >= 3
        """
        if not args:
            return CliCommandResult(False, "scenario", {}, "usage: scenario <name>")
        scenario = find_scenario(args[0])
        if scenario is None:
            msg = f"scenario not found: {args[0]}"
            return CliCommandResult(False, "scenario", {}, msg)
        self._reset_for_scenario(scenario)
        observe_results = []
        for message in scenario["messages"]:
            observe_results.append(
                self.memory.observe(
                    session_id=self.session_id,
                    msg=message,
                    scope_id=self.scope_id,
                )
            )
        reflection = self.memory.reflect(self.scope_id, force=True)
        recall = self.memory.recall(
            session_id=self.session_id,
            query=str(scenario.get("query", "")),
            k=min(8, self.config.max_recall_k),
            scope_id=self.scope_id,
        )
        context = self.memory.get_context(
            session_id=self.session_id,
            query=str(scenario.get("query", "")),
            scope_id=self.scope_id,
        )
        snapshot = self.memory.architecture_snapshot(self.scope_id)
        payload = {
            "scenario": scenario["name"],
            "scope_id": self.scope_id,
            "session_id": self.session_id,
            "messages": len(scenario["messages"]),
            "promoted": sum(len(result["promoted"]) for result in observe_results),
            "compressed": sum(
                1 for result in observe_results if result["compress_triggered"]
            ),
            "reflection": {
                "n_facts": reflection["n_facts"],
                "n_insights": reflection["n_insights"],
                "processed": reflection["processed"],
                "failed": reflection["failed"],
            },
            "facts": len(recall["facts"]),
            "episodes": len(recall["episodes"]),
            "subgraph_nodes": len(recall["subgraph"]["nodes"]),
            "context_chars": len(context),
            "snapshot": summarize_snapshot(snapshot),
        }
        return CliCommandResult(True, "scenario", payload, "scenario replayed")

    def _reset_for_scenario(self, scenario: Mapping[str, Any]) -> None:
        """Reset the session identity and memory object for a mock scenario.

        输入:
            scenario: mock_conversations 中的场景字典。
        输出:
            None；当前 session 切换到该场景。
        示例:
            示例输入: session._reset_for_scenario(NORMAL_MEMORY_SCENARIOS[0])
            示例输出: session.scope_id == scenario["scope_id"]
        """
        config_overrides = dict(scenario.get("config_overrides", {}))
        config_overrides.setdefault("memory_dir", self.config.memory_dir)
        self.config = MemoryConfig(**config_overrides)
        self.memory = AgentMemory(self.config)
        self.session_id = str(scenario["session_id"])
        self.scope_id = str(scenario["scope_id"])

    def _observe(self, args: Sequence[str]) -> CliCommandResult:
        """Append one L0 message and trigger normal write-side behavior.

        输入:
            args: role 和 content 参数。
        输出:
            CliCommandResult: AgentMemory.observe 的返回值。
        示例:
            示例输入: session._observe(["user", "记住", "x=y"])
            示例输出: payload["promoted"] 包含新记忆 ID。
        """
        if len(args) < 2:
            return CliCommandResult(
                False,
                "observe",
                {},
                "usage: observe <role> <content>",
            )
        role = args[0]
        content = " ".join(args[1:])
        payload = self.memory.observe(
            session_id=self.session_id,
            msg={"role": role, "content": content},
            scope_id=self.scope_id,
        )
        return CliCommandResult(True, "observe", payload, "message observed")

    def _memorize(self, args: Sequence[str]) -> CliCommandResult:
        """Promote explicit text directly into L2 memory.

        输入:
            args: 需要记忆的文本 token。
        输出:
            CliCommandResult: AgentMemory.memorize 的返回值。
        示例:
            示例输入: session._memorize(["记住", "cli.topic=memory"])
            示例输出: payload["mem_id"] 为非空字符串。
        """
        if not args:
            return CliCommandResult(False, "memorize", {}, "usage: memorize <text>")
        payload = self.memory.memorize(
            session_id=self.session_id,
            text=" ".join(args),
            scope_id=self.scope_id,
        )
        return CliCommandResult(True, "memorize", payload, "memory promoted")

    def _reflect(self, args: Sequence[str]) -> CliCommandResult:
        """Run L2 to L3/L4 consolidation.

        输入:
            args: 可选 force 或 auto。
        输出:
            CliCommandResult: AgentMemory.reflect 的返回值。
        示例:
            示例输入: session._reflect(["force"])
            示例输出: payload["n_facts"] >= 0。
        """
        force = not args or args[0].lower() == "force"
        payload = self.memory.reflect(self.scope_id, force=force)
        return CliCommandResult(True, "reflect", payload, "reflection completed")

    def _recall(
        self,
        args: Sequence[str],
        include_archived: bool,
    ) -> CliCommandResult:
        """Run recall or search against the current session.

        输入:
            args: query 和可选 k；include_archived 控制是否复活 archived 记忆。
        输出:
            CliCommandResult: AgentMemory.recall/search 的返回值。
        示例:
            示例输入: session._recall(["user.lang", "3"], True)
            示例输出: payload["facts"] 是事实列表。
        """
        if not args:
            return CliCommandResult(False, "recall", {}, "usage: recall <query> [k]")
        query, k = split_query_and_k(args, self.config.max_recall_k)
        payload = self.memory.recall(
            session_id=self.session_id,
            query=query,
            k=k,
            scope_id=self.scope_id,
            include_archived=include_archived,
        )
        command = "recall" if include_archived else "search"
        return CliCommandResult(True, command, payload, f"{command} completed")

    def _context(self, args: Sequence[str]) -> CliCommandResult:
        """Build prompt-ready memory context for the current session.

        输入:
            args: 可选 query。
        输出:
            CliCommandResult: 包含 context 文本和长度。
        示例:
            示例输入: session._context(["语言偏好"])
            示例输出: payload["context"] 包含 Facts 或 Episodes。
        """
        query = " ".join(args) if args else None
        context = self.memory.get_context(
            session_id=self.session_id,
            query=query,
            scope_id=self.scope_id,
        )
        payload = {"context": context, "chars": len(context)}
        return CliCommandResult(True, "context", payload, "context built")

    def _snapshot(self) -> CliCommandResult:
        """Return a compact cross-layer architecture snapshot.

        输入:
            self: 当前 CLI session。
        输出:
            CliCommandResult: L0-L4、inbox、persistence 摘要。
        示例:
            示例输入: session._snapshot()
            示例输出: payload["l3_facts"] >= 0。
        """
        snapshot = self.memory.architecture_snapshot(self.scope_id)
        return CliCommandResult(
            True,
            "snapshot",
            summarize_snapshot(snapshot),
            "snapshot summarized",
        )

    def _forget(self, args: Sequence[str]) -> CliCommandResult:
        """Run one forget mode against the current scope.

        输入:
            args: decay、expire 或 hard 参数。
        输出:
            CliCommandResult: AgentMemory.forget 的返回值。
        示例:
            示例输入: session._forget(["decay"])
            示例输出: payload 包含 theta_dyn。
        """
        if not args:
            return CliCommandResult(
                False,
                "forget",
                {},
                "usage: forget decay|expire|hard [mem_id] [force]",
            )
        mode = args[0]
        mem_id = args[1] if len(args) >= 2 and args[1] != "force" else None
        force = "force" in {item.lower() for item in args[1:]}
        payload = self.memory.forget(
            scope_id=self.scope_id,
            mode=mode,
            mem_id=mem_id,
            force=force,
        )
        return CliCommandResult(True, "forget", payload, "forget completed")

    def _update(self, args: Sequence[str]) -> CliCommandResult:
        """Update an L3 fact or L2 memory from CLI arguments.

        输入:
            args: fact 或 mem 子命令参数。
        输出:
            CliCommandResult: AgentMemory.update 的返回值。
        示例:
            示例输入: session._update(["fact", "user.lang", "zh", "0.9"])
            示例输出: payload["action"] 为 created 或 replaced。
        """
        if len(args) < 3:
            return CliCommandResult(
                False,
                "update",
                {},
                (
                    "usage: update fact <key> <value> [confidence] "
                    "| update mem <id> <text>"
                ),
            )
        target = args[0].lower()
        if target == "fact":
            fact_key = args[1]
            value_parts = list(args[2:])
            confidence = 0.9
            if value_parts and is_float(value_parts[-1]):
                confidence = float(value_parts.pop())
            payload = self.memory.update(
                {
                    "scope_id": self.scope_id,
                    "fact_key": fact_key,
                    "value": " ".join(value_parts),
                    "confidence": confidence,
                }
            )
            return CliCommandResult(True, "update", payload, "fact updated")
        if target == "mem":
            payload = self.memory.update(
                {
                    "scope_id": self.scope_id,
                    "mem_id": args[1],
                    "text": " ".join(args[2:]),
                }
            )
            return CliCommandResult(True, "update", payload, "memory updated")
        return CliCommandResult(
            False,
            "update",
            {},
            "update target must be fact or mem",
        )

    def _flush(self) -> CliCommandResult:
        """Persist the current scope state to the configured memory directory.

        输入:
            self: 当前 CLI session。
        输出:
            CliCommandResult: 包含 storage_path 的结果。
        示例:
            示例输入: session._flush()
            示例输出: payload["storage_path"] == ".memories/..."
        """
        storage_path = self.memory.flush(self.scope_id)
        return CliCommandResult(
            True,
            "flush",
            {"storage_path": storage_path},
            "scope state flushed",
        )

    def _state(self) -> CliCommandResult:
        """Read and summarize the persisted scope state.

        输入:
            self: 当前 CLI session。
        输出:
            CliCommandResult: 持久化状态摘要；未 flush 时 exists 为 False。
        示例:
            示例输入: session._state()
            示例输出: payload["exists"] in {True, False}
        """
        state = self.memory.read_stored_state(self.scope_id)
        if state is None:
            payload = {
                "exists": False,
                "storage_path": self.memory.storage_path(self.scope_id),
            }
        else:
            payload = {
                "exists": True,
                "storage_path": self.memory.storage_path(self.scope_id),
                "scope_id": state["scope_id"],
                "l0_sessions": len(state["l0"]),
                "l1_sessions": len(state["l1"]),
                "l2_records": len(state["l2"]),
                "l3_facts": len(state["l3"]["facts"]),
                "l4_nodes": len(state["l4"]["nodes"]),
                "l4_edges": len(state["l4"]["edges"]),
            }
        return CliCommandResult(True, "state", payload, "state loaded")

    def _view(self, args: Sequence[str]) -> CliCommandResult:
        """Render current memories as JSON, tables, or an ASCII tree.

        输入:
            args: 可选展示格式与层级过滤，例如 table l3。
        输出:
            CliCommandResult: 包含完整记录和可读渲染文本。
        示例:
            示例输入: session._view(["tree", "all"])
            示例输出: payload["rendered"] 包含 L2/L3/L4 层级内容。
        """
        view_format = "tree"
        layer = "all"
        for arg in args:
            lowered = arg.lower()
            if lowered in VIEW_FORMATS:
                view_format = lowered
            elif lowered in VIEW_LAYERS:
                layer = lowered
            else:
                return CliCommandResult(
                    False,
                    "view",
                    {"unknown_arg": arg},
                    (
                        "usage: view [tree|table|json] "
                        "[all|l0|l1|l2|l3|l4|inbox]"
                    ),
                )
        records = filter_memory_state(
            collect_memory_state(self.memory, self.scope_id, self.session_id),
            layer,
        )
        if view_format == "json":
            rendered = json.dumps(
                records,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        elif view_format == "table":
            rendered = render_memory_tables(records)
        else:
            rendered = render_memory_tree(records)
        payload = {
            "format": view_format,
            "layer": layer,
            "summary": records["summary"],
            "records": records,
            "rendered": rendered,
        }
        return CliCommandResult(True, "view", payload, "memory view rendered")

    def _validate(self, args: Sequence[str]) -> CliCommandResult:
        """Run an automated capability validation against AgentMemory.

        输入:
            args: 可选 fact_key；默认 cli.validation.store。
        输出:
            CliCommandResult: 详细检查项、能力评分和建议。
        示例:
            示例输入: session._validate([])
            示例输出: payload["summary"]["failed"] == 0。
        """
        payload = run_capability_validation(self, args)
        ok = payload["summary"]["failed"] == 0
        message = "validation passed" if ok else "validation failed"
        return CliCommandResult(ok, "validate", payload, message)


def build_memory_config(
    memory_dir: str,
    flush_turns: int = 4,
    max_recall_k: int = 20,
) -> MemoryConfig:
    """Build the default config used by the interactive CLI.

    输入:
        memory_dir: `.memories` 下的相对存储目录。
        flush_turns: L0 压缩触发轮数。
        max_recall_k: recall/search 最大返回数量。
    输出:
        MemoryConfig: CLI 调试用配置。
    示例:
        示例输入: build_memory_config(".memories/mem-cli")
        示例输出: MemoryConfig(flush_turns=4, max_recall_k=20, ...)
    """
    return MemoryConfig(
        memory_dir=memory_dir,
        flush_turns=flush_turns,
        raw_window_turns=max(flush_turns * 2, 4),
        working_memory_tokens=256,
        reflect_importance_threshold=1,
        max_recall_k=max_recall_k,
        retrieval_candidate_multiplier=3,
    )


def find_scenario(name: str) -> Optional[Dict[str, Any]]:
    """Find one mock scenario by name.

    输入:
        name: scenario 名称。
    输出:
        dict | None: 匹配到的 scenario；不存在时返回 None。
    示例:
        示例输入: find_scenario("product_engineer_memory_flow")
        示例输出: {"name": "product_engineer_memory_flow", ...}
    """
    for scenarios in ALL_MOCK_SCENARIO_GROUPS.values():
        for scenario in scenarios:
            if scenario["name"] == name and is_replay_scenario(scenario):
                return scenario
    return None


def is_replay_scenario(scenario: Mapping[str, Any]) -> bool:
    """Return whether a mock scenario can be replayed by the CLI.

    输入:
        scenario: mock_conversations 中的场景或异常用例。
    输出:
    示例:
        示例输入: is_replay_scenario({"messages": [], "scope_id": "t"})
        示例输出: False
    """
    required = {"messages", "scope_id", "session_id"}
    return required <= set(scenario)


def split_query_and_k(args: Sequence[str], default_k: int) -> tuple[str, int]:
    """Split trailing recall size from query tokens.

    输入:
        args: query tokens，可选最后一项为整数 k。
        default_k: 未传 k 时的默认值。
    输出:
        tuple[str, int]: query 文本和 k。
    示例:
        示例输入: split_query_and_k(["语言", "3"], 8)
        示例输出: ("语言", 3)
    """
    if args and args[-1].isdigit():
        return " ".join(args[:-1]), int(args[-1])
    return " ".join(args), min(default_k, 8)


def is_float(value: str) -> bool:
    """Return whether a string can be parsed as float.

    输入:
        value: 待检查字符串。
    输出:
        bool: 可解析为 float 时为 True。
    示例:
        示例输入: is_float("0.9")
        示例输出: True
    """
    try:
        float(value)
    except ValueError:
        return False
    return True


def summarize_snapshot(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Reduce a full architecture snapshot to CLI-friendly counters.

    输入:
        snapshot: AgentMemory.architecture_snapshot 返回值。
    输出:
        dict: 适合命令行查看的 L0-L4 摘要。
    示例:
        示例输入: summarize_snapshot({"scope_id": "t", "l2": {"active": 1}, ...})
        示例输出: {"scope_id": "t", "l2_active": 1, ...}
    """
    return {
        "scope_id": snapshot["scope_id"],
        "l0_sessions": len(snapshot["l0_sessions"]),
        "l1_sessions": len(snapshot["l1_sessions"]),
        "l2_active": snapshot["l2"]["active"],
        "l2_archived": snapshot["l2"]["archived"],
        "l2_deleted": snapshot["l2"]["deleted"],
        "l2_occupancy": snapshot["l2"]["occupancy"],
        "l3_facts": snapshot["l3"]["facts"],
        "l3_conflicts": snapshot["l3"]["conflicts"],
        "l4_nodes": snapshot["l4"]["nodes"],
        "l4_edges": snapshot["l4"]["edges"],
        "inbox": snapshot["inbox"],
        "persistence": snapshot["persistence"],
        "backend": snapshot["backend"]["profile"],
    }


def collect_memory_state(
    memory: AgentMemory,
    scope_id: str,
    session_id: str,
) -> Dict[str, Any]:
    """Collect all visible MemX layers for CLI visualization.

    输入:
        memory: AgentMemory 实例。
        scope_id: 当前作用域 ID。
        session_id: 当前默认会话 ID。
    输出:
        dict: L0-L4、inbox 和汇总指标。
    示例:
        示例输入: collect_memory_state(memory, "scope", "s1")
        示例输出: {"l2": [...], "l3": {"facts": [...]}, ...}
    """
    l0 = memory.l0.snapshot(scope_id)
    l1 = []
    for identity in sorted(
        memory.l1.active_sessions(scope_id),
        key=lambda item: item.session_id,
    ):
        active = memory.l1.get_active_context(
            identity.session_id,
            identity.scope_id,
        )
        l1.append(
            {
                "session_id": active.session_id,
                "scope_id": active.scope_id,
                "rolling_summary": active.rolling_summary,
                "open_slots": list(active.open_slots),
                "mentioned_entities": list(active.mentioned_entities),
                "token_used": active.token_used,
                "last_compress_ts": active.last_compress_ts,
            }
        )
    l2 = sorted(
        (record.to_dict() for record in memory.l2.all_records(scope_id)),
        key=lambda item: (str(item["status"]), str(item["mem_id"])),
    )
    facts = sorted(
        (fact.to_dict() for fact in memory.l3.all_facts(scope_id)),
        key=lambda item: (str(item["fact_key"]), int(item["version"])),
    )
    conflicts = sorted(
        memory.l3.conflict_log(scope_id),
        key=lambda item: str(item["conflict_id"]),
    )
    nodes = sorted(
        (node.to_dict() for node in memory.l4.all_nodes(scope_id)),
        key=lambda item: (str(item["type"]), str(item["label"]), str(item["id"])),
    )
    edges = sorted(
        (edge.to_dict() for edge in memory.l4.all_edges(scope_id)),
        key=lambda item: (
            str(item["source"]),
            str(item["target"]),
            str(item["type"]),
        ),
    )
    inbox = sorted(
        memory.inbox.snapshot(scope_id),
        key=lambda item: str(item["item_id"]),
    )
    l0_messages = sum(len(messages) for messages in l0.values())
    summary = {
        "scope_id": scope_id,
        "session_id": session_id,
        "l0_messages": l0_messages,
        "l1_sessions": len(l1),
        "l2_records": len(l2),
        "l2_active": sum(1 for item in l2 if item["status"] == "active"),
        "l2_archived": sum(1 for item in l2 if item["status"] == "archived"),
        "l2_deleted": sum(1 for item in l2 if item["status"] == "deleted"),
        "l3_facts": len(facts),
        "l3_conflicts": len(conflicts),
        "l4_nodes": len(nodes),
        "l4_edges": len(edges),
        "inbox_items": len(inbox),
        "storage_path": memory.storage_path(scope_id),
        "stored_state_exists": memory.read_stored_state(scope_id) is not None,
    }
    return {
        "scope_id": scope_id,
        "session_id": session_id,
        "memory_dir": memory.config.memory_dir,
        "summary": summary,
        "l0": l0,
        "l1": l1,
        "l2": l2,
        "l3": {"facts": facts, "conflicts": conflicts},
        "l4": {"nodes": nodes, "edges": edges},
        "inbox": inbox,
    }


def filter_memory_state(state: Mapping[str, Any], layer: str) -> Dict[str, Any]:
    """Filter a collected memory state to one display layer.

    输入:
        state: collect_memory_state 返回的完整状态。
        layer: all、l0、l1、l2、l3、l4 或 inbox。
    输出:
        dict: 仅包含请求层级和共享元数据的状态。
    示例:
        示例输入: filter_memory_state(state, "l3")
        示例输出: {"l3": {"facts": [...]}, "summary": ...}
    """
    filtered: Dict[str, Any] = {
        "scope_id": state["scope_id"],
        "session_id": state["session_id"],
        "memory_dir": state["memory_dir"],
        "summary": state["summary"],
    }
    keys = ["l0", "l1", "l2", "l3", "l4", "inbox"] if layer == "all" else [layer]
    for key in keys:
        filtered[key] = state[key]
    return filtered


def render_memory_tree(state: Mapping[str, Any]) -> str:
    """Render memory state as an ASCII tree.

    输入:
        state: collect_memory_state/filter_memory_state 返回的状态。
    输出:
        str: 树形文本，包含内容和元数据。
    示例:
        示例输入: render_memory_tree({"scope_id": "s", ...})
        示例输出: "scope_id: s\n..."
    """
    lines = [
        f"scope_id: {state['scope_id']}",
        f"session_id: {state['session_id']}",
        f"memory_dir: {state['memory_dir']}",
    ]
    if "l0" in state:
        append_l0_tree(lines, state["l0"])
    if "l1" in state:
        append_l1_tree(lines, state["l1"])
    if "l2" in state:
        append_l2_tree(lines, state["l2"])
    if "l3" in state:
        append_l3_tree(lines, state["l3"])
    if "l4" in state:
        append_l4_tree(lines, state["l4"])
    if "inbox" in state:
        append_inbox_tree(lines, state["inbox"])
    return "\n".join(lines)


def append_l0_tree(lines: List[str], l0: Mapping[str, Any]) -> None:
    """Append L0 raw messages to a tree rendering.

    输入:
        lines: 输出文本行。
        l0: session_id 到消息列表的映射。
    输出:
        None。
    示例:
        示例输入: append_l0_tree([], {"s1": []})
        示例输出: lines 增加 L0 标题。
    """
    total = sum(len(messages) for messages in l0.values())
    lines.append(f"l0 raw messages ({total})")
    if not l0:
        lines.append("  (empty)")
        return
    for session_id, messages in sorted(l0.items()):
        lines.append(f"  session {session_id} ({len(messages)})")
        for message in messages:
            line = (
                f"    turn={message['turn_id']} role={message['role']} "
                f"tokens={message['token_len']} content={message['content']}"
            )
            lines.append(line)


def append_l1_tree(lines: List[str], l1: Sequence[Mapping[str, Any]]) -> None:
    """Append L1 working memory sessions to a tree rendering.

    输入:
        lines: 输出文本行。
        l1: L1 session 列表。
    输出:
        None。
    示例:
        示例输入: append_l1_tree([], [])
        示例输出: lines 增加空 L1 标题。
    """
    lines.append(f"l1 working memory ({len(l1)})")
    if not l1:
        lines.append("  (empty)")
        return
    for item in l1:
        lines.append(
            f"  session={item['session_id']} tokens={item['token_used']}"
        )
        lines.append(f"    summary={item['rolling_summary']}")
        lines.append(f"    open_slots={format_value(item['open_slots'])}")
        lines.append(f"    entities={format_value(item['mentioned_entities'])}")


def append_l2_tree(lines: List[str], l2: Sequence[Mapping[str, Any]]) -> None:
    """Append L2 episodic memories to a tree rendering.

    输入:
        lines: 输出文本行。
        l2: L2 record 列表。
    输出:
        None。
    示例:
        示例输入: append_l2_tree([], [])
        示例输出: lines 增加空 L2 标题。
    """
    lines.append(f"l2 episodic memories ({len(l2)})")
    if not l2:
        lines.append("  (empty)")
        return
    for item in l2:
        header = (
            f"  mem_id={item['mem_id']} status={item['status']} "
            f"type={item['mem_type']} importance={item['importance']}"
        )
        lines.append(header)
        lines.append(
            f"    access_count={item['access_count']} "
            f"stability={round(float(item['stability']), 3)}"
        )
        lines.append(f"    source_ids={format_value(item['source_ids'])}")
        lines.append(f"    text={item['text']}")


def append_l3_tree(lines: List[str], l3: Mapping[str, Any]) -> None:
    """Append L3 facts and conflicts to a tree rendering.

    输入:
        lines: 输出文本行。
        l3: facts/conflicts 字典。
    输出:
        None。
    示例:
        示例输入: append_l3_tree([], {"facts": [], "conflicts": []})
        示例输出: lines 增加 L3 标题。
    """
    facts = l3["facts"]
    conflicts = l3["conflicts"]
    lines.append(f"l3 semantic facts ({len(facts)})")
    if not facts:
        lines.append("  (empty)")
    for item in facts:
        lines.append(
            f"  {item['fact_key']}={item['value']} "
            f"confidence={round(float(item['confidence']), 3)} "
            f"version={item['version']} partition={item['partition']}"
        )
        lines.append(f"    evidence_ids={format_value(item['evidence_ids'])}")
    lines.append(f"l3 conflict log ({len(conflicts)})")
    if not conflicts:
        lines.append("  (empty)")
    for item in conflicts:
        lines.append(
            f"  conflict_id={item['conflict_id']} fact_key={item['fact_key']} "
            f"action={item['action']} severity={item['severity']}"
        )


def append_l4_tree(lines: List[str], l4: Mapping[str, Any]) -> None:
    """Append L4 graph nodes and edges to a tree rendering.

    输入:
        lines: 输出文本行。
        l4: nodes/edges 字典。
    输出:
        None。
    示例:
        示例输入: append_l4_tree([], {"nodes": [], "edges": []})
        示例输出: lines 增加 L4 标题。
    """
    nodes = l4["nodes"]
    edges = l4["edges"]
    lines.append(f"l4 cognitive graph nodes ({len(nodes)})")
    if not nodes:
        lines.append("  (empty)")
    for item in nodes:
        lines.append(
            f"  id={item['id']} type={item['type']} label={item['label']} "
            f"salience={round(float(item['salience']), 3)} "
            f"status={item['status']}"
        )
        lines.append(f"    evidence_ids={format_value(item['evidence_ids'])}")
    lines.append(f"l4 cognitive graph edges ({len(edges)})")
    if not edges:
        lines.append("  (empty)")
    for item in edges:
        lines.append(
            f"  {item['source']} -> {item['target']} "
            f"type={item['type']} weight={round(float(item['weight']), 3)}"
        )


def append_inbox_tree(lines: List[str], inbox: Sequence[Mapping[str, Any]]) -> None:
    """Append consolidation inbox items to a tree rendering.

    输入:
        lines: 输出文本行。
        inbox: inbox item 列表。
    输出:
        None。
    示例:
        示例输入: append_inbox_tree([], [])
        示例输出: lines 增加空 inbox 标题。
    """
    lines.append(f"inbox consolidation queue ({len(inbox)})")
    if not inbox:
        lines.append("  (empty)")
        return
    for item in inbox:
        lines.append(
            f"  item_id={item['item_id']} mem_id={item['mem_id']} "
            f"status={item['status']} priority={item['priority']}"
        )
        lines.append(f"    text={item['text']}")


def render_memory_tables(state: Mapping[str, Any]) -> str:
    """Render memory state as one or more ASCII tables.

    输入:
        state: collect_memory_state/filter_memory_state 返回的状态。
    输出:
        str: 表格文本。
    示例:
        示例输入: render_memory_tables(state)
        示例输出: "+---" 风格的表格。
    """
    sections = [
        f"scope_id: {state['scope_id']}",
        f"session_id: {state['session_id']}",
        f"memory_dir: {state['memory_dir']}",
    ]
    if "l0" in state:
        sections.append(render_l0_table(state["l0"]))
    if "l1" in state:
        sections.append(render_ascii_table("l1 working memory", [
            "session",
            "tokens",
            "summary",
            "open_slots",
            "entities",
        ], [
            [
                item["session_id"],
                item["token_used"],
                item["rolling_summary"],
                item["open_slots"],
                item["mentioned_entities"],
            ]
            for item in state["l1"]
        ]))
    if "l2" in state:
        sections.append(render_ascii_table("l2 episodic memories", [
            "mem_id",
            "status",
            "type",
            "importance",
            "access",
            "text",
        ], [
            [
                item["mem_id"],
                item["status"],
                item["mem_type"],
                item["importance"],
                item["access_count"],
                item["text"],
            ]
            for item in state["l2"]
        ]))
    if "l3" in state:
        sections.append(render_l3_tables(state["l3"]))
    if "l4" in state:
        sections.append(render_l4_tables(state["l4"]))
    if "inbox" in state:
        sections.append(render_ascii_table("inbox consolidation queue", [
            "item_id",
            "mem_id",
            "status",
            "priority",
            "text",
        ], [
            [
                item["item_id"],
                item["mem_id"],
                item["status"],
                item["priority"],
                item["text"],
            ]
            for item in state["inbox"]
        ]))
    return "\n\n".join(sections)


def render_l0_table(l0: Mapping[str, Any]) -> str:
    """Render L0 messages as an ASCII table.

    输入:
        l0: session_id 到消息列表的映射。
    输出:
        str: L0 表格文本。
    示例:
        示例输入: render_l0_table({"s1": []})
        示例输出: "l0 raw messages\n(empty)"。
    """
    rows = []
    for session_id, messages in sorted(l0.items()):
        for item in messages:
            rows.append(
                [
                    session_id,
                    item["turn_id"],
                    item["role"],
                    item["token_len"],
                    item["content"],
                ]
            )
    return render_ascii_table(
        "l0 raw messages",
        ["session", "turn", "role", "tokens", "content"],
        rows,
    )


def render_l3_tables(l3: Mapping[str, Any]) -> str:
    """Render L3 facts and conflict logs as ASCII tables.

    输入:
        l3: facts/conflicts 字典。
    输出:
        str: L3 表格文本。
    示例:
        示例输入: render_l3_tables({"facts": [], "conflicts": []})
        示例输出: 两段 L3 表格。
    """
    facts = render_ascii_table("l3 semantic facts", [
        "fact_key",
        "value",
        "confidence",
        "version",
        "partition",
        "evidence",
    ], [
        [
            item["fact_key"],
            item["value"],
            round(float(item["confidence"]), 3),
            item["version"],
            item["partition"],
            item["evidence_ids"],
        ]
        for item in l3["facts"]
    ])
    conflicts = render_ascii_table("l3 conflict log", [
        "conflict_id",
        "fact_key",
        "type",
        "severity",
        "action",
    ], [
        [
            item["conflict_id"],
            item["fact_key"],
            item["conflict_type"],
            item["severity"],
            item["action"],
        ]
        for item in l3["conflicts"]
    ])
    return f"{facts}\n\n{conflicts}"


def render_l4_tables(l4: Mapping[str, Any]) -> str:
    """Render L4 graph nodes and edges as ASCII tables.

    输入:
        l4: nodes/edges 字典。
    输出:
        str: L4 表格文本。
    示例:
        示例输入: render_l4_tables({"nodes": [], "edges": []})
        示例输出: 两段 L4 表格。
    """
    nodes = render_ascii_table("l4 cognitive graph nodes", [
        "id",
        "type",
        "label",
        "salience",
        "status",
        "evidence",
    ], [
        [
            item["id"],
            item["type"],
            item["label"],
            round(float(item["salience"]), 3),
            item["status"],
            item["evidence_ids"],
        ]
        for item in l4["nodes"]
    ])
    edges = render_ascii_table("l4 cognitive graph edges", [
        "source",
        "target",
        "type",
        "weight",
    ], [
        [
            item["source"],
            item["target"],
            item["type"],
            round(float(item["weight"]), 3),
        ]
        for item in l4["edges"]
    ])
    return f"{nodes}\n\n{edges}"


def render_ascii_table(
    title: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> str:
    """Render rows as a compact ASCII table.

    输入:
        title: 表格标题。
        headers: 表头字段。
        rows: 单元格数据行。
    输出:
        str: ASCII 表格。
    示例:
        示例输入: render_ascii_table("t", ["a"], [[1]])
        示例输出: "t\n+---+..."。
    """
    if not rows:
        return f"{title}\n(empty)"
    rendered_rows = [[format_cell(value) for value in row] for row in rows]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rendered_rows))
        for index in range(len(headers))
    ]
    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    header = "| " + " | ".join(
        headers[index].ljust(widths[index]) for index in range(len(headers))
    ) + " |"
    body = [
        "| " + " | ".join(
            row[index].ljust(widths[index]) for index in range(len(headers))
        ) + " |"
        for row in rendered_rows
    ]
    return "\n".join([title, separator, header, separator, *body, separator])


def format_cell(value: Any, max_width: int = 72) -> str:
    """Format one value for table display.

    输入:
        value: 任意可 JSON 序列化或可字符串化的值。
        max_width: 单元格最大宽度。
    输出:
        str: 单行展示文本。
    示例:
        示例输入: format_cell(["a", "b"])
        示例输出: "[\"a\", \"b\"]"。
    """
    text = format_value(value)
    if len(text) <= max_width:
        return text
    return text[: max_width - 3] + "..."


def format_value(value: Any) -> str:
    """Format a scalar or collection as one line.

    输入:
        value: 待展示值。
    输出:
        str: 单行字符串。
    示例:
        示例输入: format_value({"a": 1})
        示例输出: "{\"a\": 1}"。
    """
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return " ".join(text.splitlines())


def run_capability_validation(
    session: MemoryCliSession,
    args: Sequence[str],
) -> Dict[str, Any]:
    """Exercise store, retrieval, update, delete, view, and persistence paths.

    输入:
        session: 当前 MemoryCliSession。
        args: 可选 fact_key。
    输出:
        dict: 自动化验证报告。
    示例:
        示例输入: run_capability_validation(session, [])
        示例输出: {"summary": {"failed": 0}, "checks": [...]}。
    """
    fact_key = args[0] if args else "cli.validation.store"
    initial_text = f"记住 {fact_key}=ok"
    updated_text = f"记住 {fact_key}=updated"
    checks: List[Dict[str, Any]] = []

    def add_check(name: str, ok: bool, details: Mapping[str, Any]) -> None:
        checks.append(
            {
                "name": name,
                "ok": ok,
                "details": dict(details),
            }
        )

    diagnostics = session.memory.backend_diagnostics()
    add_check(
        "agents_and_memory_modules_connected",
        (
            type(session.memory).__name__ == "AgentMemory"
            and hasattr(session.memory, "recall_agent")
            and hasattr(session.memory, "consolidation_agent")
            and diagnostics["profile"] == "memory"
        ),
        {
            "agent": type(session.memory).__name__,
            "recall_agent": type(session.memory.recall_agent).__name__,
            "consolidation_agent": type(
                session.memory.consolidation_agent
            ).__name__,
            "backend_profile": diagnostics["profile"],
            "memory_dir": session.config.memory_dir,
        },
    )

    mem_id = ""
    try:
        stored = session.memory.memorize(
            session_id=session.session_id,
            text=initial_text,
            scope_id=session.scope_id,
        )
        mem_id = str(stored["mem_id"])
        add_check(
            "memory_store",
            bool(mem_id),
            {"mem_id": mem_id, "storage_path": stored["storage_path"]},
        )
    except Exception as exc:  # noqa: BLE001 - validation reports all failures.
        add_check("memory_store", False, error_details(exc))

    try:
        reflected = session.memory.reflect(session.scope_id, force=True)
        add_check(
            "memory_reflect",
            reflected["n_facts"] >= 1,
            {
                "n_facts": reflected["n_facts"],
                "n_insights": reflected["n_insights"],
                "processed": reflected["processed"],
                "failed": reflected["failed"],
            },
        )
    except Exception as exc:  # noqa: BLE001
        add_check("memory_reflect", False, error_details(exc))

    try:
        recalled = session.memory.recall(
            session_id=session.session_id,
            query=fact_key,
            k=5,
            scope_id=session.scope_id,
        )
        matching_facts = [
            fact for fact in recalled["facts"] if fact["fact_key"] == fact_key
        ]
        add_check(
            "memory_retrieval",
            bool(matching_facts),
            {
                "facts": len(recalled["facts"]),
                "episodes": len(recalled["episodes"]),
                "matched_fact_keys": [
                    fact["fact_key"] for fact in matching_facts
                ],
            },
        )
    except Exception as exc:  # noqa: BLE001
        add_check("memory_retrieval", False, error_details(exc))

    try:
        update_result = session.memory.update(
            {
                "scope_id": session.scope_id,
                "fact_key": fact_key,
                "value": "updated",
                "confidence": 0.97,
            }
        )
        if mem_id:
            session.memory.update(
                {
                    "scope_id": session.scope_id,
                    "mem_id": mem_id,
                    "text": updated_text,
                }
            )
        recalled_after_update = session.memory.recall(
            session_id=session.session_id,
            query=fact_key,
            k=5,
            scope_id=session.scope_id,
        )
        latest_values = [
            fact["value"]
            for fact in recalled_after_update["facts"]
            if fact["fact_key"] == fact_key
        ]
        add_check(
            "memory_update",
            "updated" in latest_values,
            {
                "fact_action": update_result["action"],
                "latest_values": latest_values,
                "mem_id": mem_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        add_check("memory_update", False, error_details(exc))

    try:
        delete_result = session.memory.forget(
            scope_id=session.scope_id,
            mode="hard",
            mem_id=mem_id,
            force=True,
        )
        record = session.memory.l2.get(mem_id, session.scope_id) if mem_id else None
        deleted = record is not None and record.status.value == "deleted"
        add_check(
            "memory_delete",
            delete_result.get("deleted") == 1 and deleted,
            {
                "mem_id": mem_id,
                "deleted": delete_result.get("deleted"),
                "status": record.status.value if record is not None else "missing",
            },
        )
    except Exception as exc:  # noqa: BLE001
        add_check("memory_delete", False, error_details(exc))

    try:
        state = collect_memory_state(
            session.memory,
            session.scope_id,
            session.session_id,
        )
        tree = render_memory_tree(state)
        table = render_memory_tables(filter_memory_state(state, "l3"))
        ok = fact_key in tree and "l3 semantic facts" in table
        add_check(
            "memory_visualization",
            ok,
            {
                "tree_chars": len(tree),
                "table_chars": len(table),
                "l2_records": state["summary"]["l2_records"],
                "l3_facts": state["summary"]["l3_facts"],
            },
        )
    except Exception as exc:  # noqa: BLE001
        add_check("memory_visualization", False, error_details(exc))

    try:
        storage_path = session.memory.flush(session.scope_id)
        stored_state = session.memory.read_stored_state(session.scope_id)
        add_check(
            "memory_persistence",
            stored_state is not None,
            {
                "storage_path": storage_path,
                "l2_records": len(stored_state["l2"]) if stored_state else 0,
                "l3_facts": (
                    len(stored_state["l3"]["facts"]) if stored_state else 0
                ),
            },
        )
    except Exception as exc:  # noqa: BLE001
        add_check("memory_persistence", False, error_details(exc))

    return build_validation_report(checks, fact_key, session.scope_id)


def build_validation_report(
    checks: Sequence[Mapping[str, Any]],
    fact_key: str,
    scope_id: str,
) -> Dict[str, Any]:
    """Build a scored validation report from individual checks.

    输入:
        checks: 检查项列表。
        fact_key: 本次验证使用的 fact_key。
        scope_id: 当前作用域。
    输出:
        dict: 汇总、能力矩阵和建议。
    示例:
        示例输入: build_validation_report([{"ok": True}], "k", "s")
        示例输出: {"summary": {"passed": 1, ...}}。
    """
    passed = sum(1 for check in checks if check["ok"])
    failed = len(checks) - passed
    score = round(passed / len(checks), 3) if checks else 0.0
    capabilities = {
        "connect_agents_and_memories": capability_status(
            checks, "agents_and_memory_modules_connected"
        ),
        "store": capability_status(checks, "memory_store"),
        "retrieve": capability_status(checks, "memory_retrieval"),
        "update": capability_status(checks, "memory_update"),
        "delete": capability_status(checks, "memory_delete"),
        "visualize": capability_status(checks, "memory_visualization"),
        "persist": capability_status(checks, "memory_persistence"),
    }
    return {
        "summary": {
            "scope_id": scope_id,
            "fact_key": fact_key,
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "score": score,
            "rating": "pass" if failed == 0 else "fail",
        },
        "capabilities": capabilities,
        "checks": list(checks),
        "recommendations": validation_recommendations(checks),
    }


def capability_status(checks: Sequence[Mapping[str, Any]], name: str) -> str:
    """Return pass/fail/missing status for one named validation check.

    输入:
        checks: 检查项列表。
        name: 检查项名称。
    输出:
        str: pass、fail 或 missing。
    示例:
        示例输入: capability_status([{"name": "x", "ok": True}], "x")
        示例输出: "pass"。
    """
    for check in checks:
        if check["name"] == name:
            return "pass" if check["ok"] else "fail"
    return "missing"


def validation_recommendations(
    checks: Sequence[Mapping[str, Any]],
) -> List[str]:
    """Generate actionable recommendations for failed checks.

    输入:
        checks: 检查项列表。
    输出:
        list[str]: 修复建议；全部通过时为空。
    示例:
        示例输入: validation_recommendations([{"name": "x", "ok": False}])
        示例输出: ["检查 x 的 details 字段。"]。
    """
    recommendations = []
    for check in checks:
        if not check["ok"]:
            recommendations.append(f"检查 {check['name']} 的 details 字段。")
    return recommendations


def error_details(exc: Exception) -> Dict[str, str]:
    """Return a JSON-compatible error description.

    输入:
        exc: 捕获到的异常。
    输出:
        dict: error_type 和 message。
    示例:
        示例输入: error_details(ValueError("bad"))
        示例输出: {"error_type": "ValueError", "message": "bad"}。
    """
    return {"error_type": type(exc).__name__, "message": str(exc)}


def dump_result(result: CliCommandResult, output: TextIO) -> None:
    """Write one command result as JSON Lines.

    输入:
        result: CLI 命令执行结果。
        output: 输出流。
    输出:
        None；写入一行 JSON。
    示例:
        示例输入: dump_result(CliCommandResult(True, "help", {}), sys.stdout)
        示例输出: stdout 写入 {"ok": true, ...}
    """
    output.write(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    output.write("\n")
    output.flush()


def run_repl(
    session: MemoryCliSession,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    """Run the interactive command loop.

    输入:
        session: CLI session。
        input_stream: 命令输入流。
        output_stream: JSON 输出流。
    输出:
        int: 退出码，全部命令成功为 0，否则为 1。
    示例:
        示例输入: run_repl(session, StringIO("help\nexit\n"), output)
        示例输出: 0
    """
    had_error = False
    interactive = input_stream.isatty()
    while True:
        if interactive:
            output_stream.write("mem> ")
            output_stream.flush()
        line = input_stream.readline()
        if not line:
            break
        result = session.run_command(line)
        had_error = had_error or not result.ok
        dump_result(result, output_stream)
        if result.exit_requested:
            break
    return 1 if had_error else 0


def run_scripted_commands(
    session: MemoryCliSession,
    commands: Iterable[str],
    output_stream: TextIO,
) -> int:
    """Run a finite command list and print JSON results.

    输入:
        session: CLI session。
        commands: 命令字符串序列。
        output_stream: 输出流。
    输出:
        int: 任一命令失败返回 1，否则返回 0。
    示例:
        示例输入: run_scripted_commands(session, ["help"], output)
        示例输出: 0
    """
    had_error = False
    for command in commands:
        result = session.run_command(command)
        had_error = had_error or not result.ok
        dump_result(result, output_stream)
        if result.exit_requested:
            break
    return 1 if had_error else 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI process arguments.

    输入:
        argv: 可选命令行参数；None 表示读取 sys.argv。
    输出:
        argparse.Namespace: 解析后的参数对象。
    示例:
        示例输入: parse_args(["--command", "help"])
        示例输出: Namespace(command=["help"], ...)
    """
    parser = argparse.ArgumentParser(
        description="Interactive CLI for testing MemX capabilities.",
    )
    parser.add_argument("--memory-dir", default=DEFAULT_MEMORY_DIR)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--scope-id", default=DEFAULT_SCOPE_ID)
    parser.add_argument("--flush-turns", type=int, default=4)
    parser.add_argument("--max-recall-k", type=int, default=20)
    parser.add_argument("--list-scenarios", action="store_true")
    parser.add_argument("--scenario", help="Replay a mock scenario before commands.")
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        help="Run one command non-interactively; can be passed multiple times.",
    )
    parser.add_argument(
        "--no-repl",
        action="store_true",
        help="Exit after --list-scenarios, --scenario, or --command.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the MemX interactive CLI entrypoint.

    输入:
        argv: 可选命令行参数。
    输出:
        int: 进程退出码。
    示例:
        示例输入: main(["--command", "help"])
        示例输出: 0
    """
    args = parse_args(argv)
    config = build_memory_config(
        args.memory_dir,
        flush_turns=args.flush_turns,
        max_recall_k=args.max_recall_k,
    )
    session = MemoryCliSession(
        config=config,
        session_id=args.session_id,
        scope_id=args.scope_id,
    )
    commands: List[str] = []
    if args.list_scenarios:
        commands.append("list")
    if args.scenario:
        commands.append(f"scenario {shlex.quote(args.scenario)}")
    commands.extend(args.command)
    if commands:
        exit_code = run_scripted_commands(session, commands, sys.stdout)
        if args.no_repl or args.command:
            return exit_code
        repl_code = run_repl(session)
        return exit_code or repl_code
    if args.no_repl:
        return 0
    return run_repl(session)


if __name__ == "__main__":
    raise SystemExit(main())
