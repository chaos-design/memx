"""Message parsing and conversion helpers for CLI memory ingestion."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..memory.models import Role
from .result import CliError

INPUT_FORMAT_CHOICES = ("auto", "text", "json", "jsonl")
OUTPUT_FORMAT_CHOICES = ("json", "jsonl")
STORE_MODE_CHOICES = ("observe", "memorize", "none")
ROLE_CHOICES = tuple(role.value for role in Role)
CONTENT_KEYS = ("content", "text", "message")
RESERVED_JSON_KEYS = frozenset(("role", "content", "text", "message", "ts", "metadata"))


@dataclass(frozen=True)
class ParsedMessage:
    """Normalized message ready for conversion to the memories structure.

    Example Input:
        ParsedMessage(role="user", content="记住 user.lang=zh", source="stdin")
    Example Output:
        message.to_memory_dict("s1", "scope") returns a JSON-compatible dict.
    """

    role: str
    content: str
    ts: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    source: str = "stdin"
    index: int = 1

    def to_memory_dict(self, session_id: str, scope_id: str) -> Dict[str, Any]:
        """Return the CLI-level memories representation.

        Example Input:
            message.to_memory_dict("s1", "scope-a")
        Example Output:
            {"role": "user", "content": "...", "session_id": "s1", ...}
        """
        item: Dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "session_id": session_id,
            "scope_id": scope_id,
            "source": f"{self.source}:{self.index}",
        }
        if self.ts is not None:
            item["ts"] = self.ts
        if self.metadata:
            item["metadata"] = dict(self.metadata)
        return item

    def to_observe_message(self) -> Dict[str, Any]:
        """Return a payload accepted by AgentMemory.observe.

        Example Input:
            ParsedMessage("user", "hello").to_observe_message()
        Example Output:
            {"role": "user", "content": "hello"}
        """
        payload: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.ts is not None:
            payload["ts"] = self.ts
        return payload


def parse_messages(
    raw_text: str,
    input_format: str = "auto",
    default_role: str = "user",
    source: str = "stdin",
) -> List[ParsedMessage]:
    """Parse raw CLI input into normalized messages.

    Example Input:
        parse_messages("assistant: hi", input_format="text")
    Example Output:
        [ParsedMessage(role="assistant", content="hi", ...)]
    """
    format_name = _validate_choice(input_format, INPUT_FORMAT_CHOICES, "input_format")
    role = normalize_role(default_role)
    if not raw_text.strip():
        msg = "input does not contain any message content."
        raise CliError(msg)
    if format_name == "text":
        messages = _parse_text_lines(raw_text, role, source)
    elif format_name == "json":
        messages = _parse_json_document(raw_text, role, source)
    elif format_name == "jsonl":
        messages = _parse_json_lines(raw_text, role, source)
    else:
        messages = _parse_auto(raw_text, role, source)
    if not messages:
        msg = "input did not produce any valid message."
        raise CliError(msg)
    return messages


def format_messages(
    messages: Sequence[Mapping[str, Any]],
    output_format: str = "json",
    pretty: bool = False,
) -> str:
    """Serialize converted memories for stdout payloads or output files.

    Example Input:
        format_messages([{"role": "user", "content": "hi"}], "jsonl")
    Example Output:
        '{"role":"user","content":"hi"}\\n'
    """
    format_name = _validate_choice(
        output_format,
        OUTPUT_FORMAT_CHOICES,
        "output_format",
    )
    if format_name == "jsonl":
        lines = [
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for item in messages
        ]
        return "\n".join(lines) + ("\n" if lines else "")
    indent = 2 if pretty else None
    separators = None if pretty else (",", ":")
    return json.dumps(
        list(messages),
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
        separators=separators,
    ) + "\n"


def normalize_role(role: str) -> str:
    """Normalize and validate a message role.

    Example Input:
        normalize_role("USER")
    Example Output:
        "user"
    """
    normalized = str(role).strip().lower()
    if normalized not in ROLE_CHOICES:
        msg = f"role must be one of {', '.join(ROLE_CHOICES)}."
        raise CliError(msg)
    return normalized


def _parse_auto(
    raw_text: str,
    default_role: str,
    source: str,
) -> List[ParsedMessage]:
    """Choose the most likely parser for raw input.

    Example Input:
        _parse_auto('{"content": "hi"}', "user", "stdin")
    Example Output:
        [ParsedMessage(role="user", content="hi", ...)]
    """
    stripped = raw_text.lstrip()
    if stripped.startswith("["):
        return _parse_json_document(raw_text, default_role, source)
    if stripped.startswith("{"):
        try:
            return _parse_json_document(raw_text, default_role, source)
        except CliError:
            return _parse_json_lines(raw_text, default_role, source)
    return _parse_text_lines(raw_text, default_role, source)


def _parse_text_lines(
    raw_text: str,
    default_role: str,
    source: str,
) -> List[ParsedMessage]:
    """Parse plain text where every non-empty line is one message.

    Example Input:
        _parse_text_lines("user: hello", "assistant", "stdin")
    Example Output:
        [ParsedMessage(role="user", content="hello", ...)]
    """
    messages: List[ParsedMessage] = []
    for line_no, line in enumerate(raw_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        role, content = _split_text_role(stripped, default_role)
        messages.append(
            ParsedMessage(
                role=role,
                content=content,
                source=source,
                index=line_no,
            )
        )
    return messages


def _parse_json_document(
    raw_text: str,
    default_role: str,
    source: str,
) -> List[ParsedMessage]:
    """Parse a JSON object, string, or array of message objects.

    Example Input:
        _parse_json_document('[{"content": "hi"}]', "user", "file.json")
    Example Output:
        [ParsedMessage(role="user", content="hi", ...)]
    """
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        msg = f"invalid JSON input: {exc.msg} at line {exc.lineno} column {exc.colno}."
        raise CliError(msg) from exc
    return _messages_from_json_items(_as_json_items(parsed), default_role, source)


def _parse_json_lines(
    raw_text: str,
    default_role: str,
    source: str,
) -> List[ParsedMessage]:
    """Parse JSONL input where every non-empty line is one message.

    Example Input:
        _parse_json_lines('{"content": "hi"}\\n', "user", "input.jsonl")
    Example Output:
        [ParsedMessage(role="user", content="hi", ...)]
    """
    messages: List[ParsedMessage] = []
    for line_no, line in enumerate(raw_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            msg = (
                f"invalid JSONL input at line {line_no}: "
                f"{exc.msg} at column {exc.colno}."
            )
            raise CliError(msg) from exc
        messages.extend(
            _messages_from_json_items(
                _as_json_items(parsed),
                default_role,
                source,
                start_index=line_no,
            )
        )
    return messages


def _messages_from_json_items(
    items: Iterable[Any],
    default_role: str,
    source: str,
    start_index: int = 1,
) -> List[ParsedMessage]:
    """Convert JSON values to ParsedMessage objects.

    Example Input:
        _messages_from_json_items([{"content": "hi"}], "user", "stdin")
    Example Output:
        [ParsedMessage(role="user", content="hi", ...)]
    """
    messages = []
    for offset, item in enumerate(items):
        index = start_index + offset
        messages.append(_message_from_json_item(item, default_role, source, index))
    return messages


def _as_json_items(parsed: Any) -> List[Any]:
    """Return parsed JSON as a list of message-like items.

    Example Input:
        _as_json_items({"content": "hi"})
    Example Output:
        [{"content": "hi"}]
    """
    if isinstance(parsed, list):
        return parsed
    return [parsed]


def _message_from_json_item(
    item: Any,
    default_role: str,
    source: str,
    index: int,
) -> ParsedMessage:
    """Build one ParsedMessage from a JSON value.

    Example Input:
        _message_from_json_item({"role": "user", "content": "hi"}, "user", "x", 1)
    Example Output:
        ParsedMessage(role="user", content="hi", source="x", index=1)
    """
    if isinstance(item, str):
        return ParsedMessage(
            role=default_role,
            content=_validate_content(item, source, index),
            source=source,
            index=index,
        )
    if not isinstance(item, Mapping):
        msg = f"{source}:{index} must be a JSON object or string."
        raise CliError(msg)
    role = normalize_role(str(item.get("role") or default_role))
    content = _validate_content(_extract_content(item, source, index), source, index)
    metadata = _extract_metadata(item, source, index)
    return ParsedMessage(
        role=role,
        content=content,
        ts=_extract_ts(item, source, index),
        metadata=metadata,
        source=source,
        index=index,
    )


def _extract_content(item: Mapping[str, Any], source: str, index: int) -> Any:
    """Extract content from a JSON message object.

    Example Input:
        _extract_content({"text": "hi"}, "stdin", 1)
    Example Output:
        "hi"
    """
    for key in CONTENT_KEYS:
        if key in item:
            return item[key]
    msg = f"{source}:{index} must include one of content, text, or message."
    raise CliError(msg)


def _extract_metadata(
    item: Mapping[str, Any],
    source: str,
    index: int,
) -> Dict[str, Any]:
    """Extract explicit and extra JSON fields as metadata.

    Example Input:
        _extract_metadata({"content": "hi", "channel": "dm"}, "stdin", 1)
    Example Output:
        {"channel": "dm"}
    """
    raw_metadata = item["metadata"] if "metadata" in item else {}
    if raw_metadata is None:
        raw_metadata = {}
    if not isinstance(raw_metadata, Mapping):
        msg = f"{source}:{index} metadata must be a JSON object when provided."
        raise CliError(msg)
    metadata = dict(raw_metadata)
    for key, value in item.items():
        if key not in RESERVED_JSON_KEYS:
            metadata[key] = value
    return metadata


def _extract_ts(
    item: Mapping[str, Any],
    source: str,
    index: int,
) -> Optional[float]:
    """Extract an optional numeric timestamp.

    Example Input:
        _extract_ts({"ts": 1}, "stdin", 1)
    Example Output:
        1.0
    """
    if "ts" not in item or item["ts"] is None:
        return None
    ts = item["ts"]
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        msg = f"{source}:{index} ts must be a number when provided."
        raise CliError(msg)
    return float(ts)


def _validate_content(content: Any, source: str, index: int) -> str:
    """Validate and normalize message content.

    Example Input:
        _validate_content(" hi ", "stdin", 1)
    Example Output:
        "hi"
    """
    normalized = str(content).strip()
    if not normalized:
        msg = f"{source}:{index} content must not be empty."
        raise CliError(msg)
    return normalized


def _split_text_role(line: str, default_role: str) -> Tuple[str, str]:
    """Split an optional role prefix from a text line.

    Example Input:
        _split_text_role("assistant: ok", "user")
    Example Output:
        ("assistant", "ok")
    """
    for delimiter in (":", "："):
        head, sep, tail = line.partition(delimiter)
        if sep and head.strip().lower() in ROLE_CHOICES and tail.strip():
            return normalize_role(head), tail.strip()
    return default_role, line


def _validate_choice(value: str, choices: Sequence[str], field_name: str) -> str:
    """Validate a parser or formatter choice.

    Example Input:
        _validate_choice("json", ("json",), "format")
    Example Output:
        "json"
    """
    normalized = str(value).strip().lower()
    if normalized not in choices:
        msg = f"{field_name} must be one of {', '.join(choices)}."
        raise CliError(msg)
    return normalized
