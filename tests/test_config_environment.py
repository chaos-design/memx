"""Tests for model configuration loaded from a project dotenv file."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mem import MemoryConfig
from mem.adapters import production as prod
from mem.cli.parsing import config_to_dict
from mem.config import (
    load_memory_config,
    read_dotenv,
    read_hms_config,
    write_hms_config,
)
from mem.exceptions import ConfigurationError


def test_dotenv_parser_supports_comments_export_and_quotes(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# model config\n"
        "export MEMX_LLM_GATEWAY_URL=http://gateway.local # local\n"
        "MEMX_LLM_API_KEY='secret # value'\n",
        encoding="utf-8",
    )

    values = read_dotenv(env_path)

    assert values["MEMX_LLM_GATEWAY_URL"] == "http://gateway.local"
    assert values["MEMX_LLM_API_KEY"] == "secret # value"


def test_model_environment_precedence_and_types(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    config_path = tmp_path / "hms.json"
    env_path.write_text(
        "MEMX_LLM_GATEWAY_URL=http://file-gateway\n"
        "MEMX_LLM_API_KEY=file-key\n"
        "MEMX_LLM_MODEL=decision-v1\n"
        "MEMX_EMBEDDING_MODEL=embed-v1\n"
        "MEMX_EMBEDDING_BACKEND=gateway\n"
        "MEMX_LLM_REQUEST_TIMEOUT_SECONDS=12.5\n",
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps({"max_recall_k": 7, "llm_gateway_url": "http://legacy"}),
        encoding="utf-8",
    )

    config = load_memory_config(
        path=config_path,
        env_path=env_path,
        environ={"MEMX_LLM_GATEWAY_URL": "http://process-gateway"},
    )
    overridden = load_memory_config(
        path=config_path,
        env_path=env_path,
        environ={},
        overrides={"llm_model": "explicit-model"},
    )

    assert config.max_recall_k == 7
    assert config.llm_gateway_url == "http://process-gateway"
    assert config.llm_api_key == "file-key"
    assert config.llm_model == "decision-v1"
    assert config.embedding_model == "embed-v1"
    assert config.embedding_backend == "gateway"
    assert config.llm_request_timeout_seconds == 12.5
    assert overridden.llm_model == "explicit-model"
    assert "llm_gateway_url" not in read_hms_config(config_path)


def test_model_fields_cannot_be_persisted_to_hms_json(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="configured through .env"):
        write_hms_config({"llm_api_key": "secret"}, tmp_path / "hms.json")


@pytest.mark.parametrize(
    "content",
    [
        "MISSING_EQUALS",
        "1INVALID=value",
        "MEMX_LLM_API_KEY='unterminated",
    ],
)
def test_dotenv_parser_rejects_invalid_lines(tmp_path: Path, content: str) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(content + "\n", encoding="utf-8")

    with pytest.raises(ConfigurationError):
        read_dotenv(env_path)


def test_invalid_model_timeout_and_secret_redaction(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MEMX_LLM_REQUEST_TIMEOUT_SECONDS=slow\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="MEMX_LLM_REQUEST_TIMEOUT_SECONDS"):
        load_memory_config(env_path=env_path, environ={})

    payload = config_to_dict(MemoryConfig(llm_api_key="top-secret"))
    assert payload["llm_api_key"] == "***"


def test_http_gateway_forwards_configured_model_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = MemoryConfig(
        llm_gateway_url="http://gateway.local",
        llm_model="decision-v2",
        embedding_model="embed-v2",
        llm_request_timeout_seconds=17,
    )
    gateway = prod.HttpLLMGateway(config)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"embedding": [0.5]}'
    urlopen = MagicMock(return_value=response)
    monkeypatch.setattr(prod.urllib.request, "urlopen", urlopen)

    gateway.decide_json("classify", {"type": "object"})
    decision_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    gateway.embed("text")
    embedding_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))

    assert decision_body["model"] == "decision-v2"
    assert embedding_body["model"] == "embed-v2"
    assert gateway.timeout == 17
