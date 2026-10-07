"""Load model-only runtime settings from a project-local dotenv file."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple, Union

from ..exceptions import ConfigurationError
from .paths import project_root

EnvPath = Union[str, Path]
EnvBinding = Tuple[str, Callable[[str], object]]

DEFAULT_ENV_FILENAME = ".env"
LLM_ENV_BINDINGS: Dict[str, EnvBinding] = {
    "MEMX_LLM_GATEWAY_URL": ("llm_gateway_url", str),
    "MEMX_LLM_API_KEY": ("llm_api_key", str),
    "MEMX_LLM_MODEL": ("llm_model", str),
    "MEMX_EMBEDDING_MODEL": ("embedding_model", str),
    "MEMX_EMBEDDING_BACKEND": ("embedding_backend", str),
    "MEMX_LLM_REQUEST_TIMEOUT_SECONDS": (
        "llm_request_timeout_seconds",
        float,
    ),
}
LLM_CONFIG_FIELDS = frozenset(binding[0] for binding in LLM_ENV_BINDINGS.values())
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def default_env_path() -> Path:
    """Return the project-local model environment file path."""
    return project_root() / DEFAULT_ENV_FILENAME


def read_dotenv(path: Optional[EnvPath] = None) -> Dict[str, str]:
    """Read a strict dotenv subset without mutating the process environment."""
    env_path = Path(path) if path is not None else default_env_path()
    if not env_path.exists():
        return {}
    values: Dict[str, str] = {}
    for line_number, raw_line in enumerate(
        env_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigurationError(
                f"invalid dotenv entry at {env_path}:{line_number}"
            )
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _ENV_NAME_PATTERN.fullmatch(key):
            raise ConfigurationError(
                f"invalid dotenv key at {env_path}:{line_number}: {key}"
            )
        values[key] = _decode_dotenv_value(raw_value.strip(), env_path, line_number)
    return values


def load_llm_environment(
    path: Optional[EnvPath] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Dict[str, object]:
    """Load typed model settings with process environment taking precedence."""
    raw_values = read_dotenv(path)
    process_values = os.environ if environ is None else environ
    for env_name in LLM_ENV_BINDINGS:
        if env_name in process_values:
            raw_values[env_name] = process_values[env_name]

    loaded: Dict[str, object] = {}
    for env_name, (field_name, converter) in LLM_ENV_BINDINGS.items():
        raw_value = raw_values.get(env_name, "").strip()
        if not raw_value:
            continue
        try:
            loaded[field_name] = converter(raw_value)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"invalid value for {env_name}: {raw_value!r}"
            ) from exc
    return loaded


def _decode_dotenv_value(value: str, path: Path, line_number: int) -> str:
    """Decode quoted values and strip comments from unquoted values."""
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        try:
            decoded = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise ConfigurationError(
                f"invalid quoted dotenv value at {path}:{line_number}"
            ) from exc
        if not isinstance(decoded, str):
            raise ConfigurationError(
                f"dotenv values must be strings at {path}:{line_number}"
            )
        return decoded
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()
