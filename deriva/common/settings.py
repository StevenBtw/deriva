"""One place that reads Deriva's configuration: the home .env merged under the process environment.

Every setting comes from ``environment()``: the home folder's .env with the process environment
on top, so an exported variable or a CI secret wins over the file. The file is read again when it
changes (a save from the studio's models page applies on the next read), and nothing is written
into ``os.environ``. Typed groups hold today's defaults; dynamic names go through ``get()`` and
``model_configs()``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import ValidationInfo, field_validator
from pydantic_core import PydanticUseDefault
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from deriva.common import paths


def env_file() -> Path:
    """The .env this process reads: the one in the Deriva home folder."""
    return paths.env_file()


@lru_cache(maxsize=8)
def _parse(path: str, mtime_ns: int, size: int) -> dict[str, str]:
    """The parsed file; ``mtime_ns`` and ``size`` only make the cache key change when the file does."""
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


def read_env_file() -> dict[str, str]:
    """The home .env as name to value (empty without a file); read again when the file changes (time or size)."""
    path = env_file()
    try:
        stat = path.stat()
    except OSError:
        return {}
    return dict(_parse(str(path), stat.st_mtime_ns, stat.st_size))


def environment() -> dict[str, str]:
    """The merged configuration: the home .env with the process environment on top."""
    return {**read_env_file(), **os.environ}


def child_environment(**extra: str) -> dict[str, str]:
    """The environment for a child process such as git: the process environment (not the .env, whose keys it does not
    need) without the provider variables and API keys, with ``extra`` on top."""
    kept = {k: v for k, v in os.environ.items() if k not in PROVIDER_VARIABLES and not k.upper().endswith("_API_KEY")}
    return {**kept, **extra}


def get(name: str, default: str | None = None) -> str | None:
    """One configuration value from the merged environment."""
    return environment().get(name, default)


# The variables pydantic-ai's providers read from os.environ themselves (string models such as "mistral:...")
PROVIDER_VARIABLES = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "MISTRAL_API_KEY",
    "OLLAMA_BASE_URL",
    "OLLAMA_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "OPENAI_API_VERSION",
)
# What the process was started with: these values win and are never overwritten
_ORIGINAL_ENVIRONMENT = frozenset(os.environ)
# The provider variables export_provider_keys put into os.environ (taken out again when they leave the file)
_EXPORTED: set[str] = set()


def export_provider_keys() -> None:
    """Hand the provider variables of the home .env to the LLM client libraries, which read only os.environ.

    The only write into ``os.environ``: a variable the process was started with is never touched, and
    values from the file are refreshed on every call, so a key saved from the studio applies to the
    next LLM manager and a key removed from the file is taken out again. Nothing else from .env is exported.
    """
    file = read_env_file()
    for name in PROVIDER_VARIABLES:
        if name in _ORIGINAL_ENVIRONMENT:
            continue
        if name in file:
            os.environ[name] = file[name].strip()  # a key or URL with padding breaks the header the provider library builds
            _EXPORTED.add(name)
        elif name in _EXPORTED:
            os.environ.pop(name, None)
            _EXPORTED.discard(name)


def suppress_pydantic_ai_banner() -> None:
    """Keep pydantic-ai's first-run banner out of CLI output; the library reads the variable when it would show."""
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


class _MergedEnvironment(PydanticBaseSettingsSource):
    """The settings source of every group: ``environment()``, by env_prefix plus field name in upper case."""

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        key = f"{self.settings_cls.model_config.get('env_prefix', '')}{field_name}".upper()
        return environment().get(key), key, False

    def __call__(self) -> dict[str, Any]:
        env = environment()
        prefix = self.settings_cls.model_config.get("env_prefix", "")
        return {name: env[key] for name in self.settings_cls.model_fields if (key := f"{prefix}{name}".upper()) in env}


class _Group(BaseSettings):
    """A group of settings read from the merged environment only (no second reader of .env or os.environ)."""

    model_config = SettingsConfigDict(extra="ignore")

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):  # noqa: ARG003
        return (init_settings, _MergedEnvironment(settings_cls))

    @field_validator("*", mode="before")
    @classmethod
    def _plain_values(cls, value: Any, info: ValidationInfo) -> Any:
        """Numbers, flags and optional values: padding and quotes stripped, empty means the default. Text stays as given."""
        if isinstance(value, str) and info.field_name is not None and cls.model_fields[info.field_name].annotation is not str:
            value = value.strip().strip("'\"").strip()
            if value == "":
                raise PydanticUseDefault()
        return value


class LlmSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore")

    default_model: str | None = None
    provider: str = "azure"
    azure_api_url: str | None = None
    azure_api_key: str | None = None
    azure_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    ollama_api_url: str = "http://localhost:11434/api/chat"
    ollama_model: str = "llama3.2"
    mistral_api_key: str | None = None
    mistral_model: str = "mistral-large-latest"
    lmstudio_api_url: str = "http://localhost:1234/v1/chat/completions"
    lmstudio_model: str = "local-model"
    cache_dir: str = "workspace/cache/llm"
    cache_ttl: int = 0
    max_retries: int = 3
    timeout: int = 60
    temperature: float = 0.7
    max_tokens: int | None = None
    nocache: bool = False
    rate_limit_rpm: int = 0
    rate_limit_delay: float = 0.0
    retry_base_delay: float = 2.0
    retry_max_delay: float = 60.0
    throttle_enabled: bool = True
    throttle_min_factor: float = 0.25
    throttle_recovery_time: float = 60.0
    circuit_breaker_enabled: bool = True
    circuit_failure_threshold: int = 5
    circuit_recovery_time: float = 30.0

    @field_validator("*", mode="before")
    @classmethod
    def _credentials_plain(cls, value: Any, info: ValidationInfo) -> Any:
        """Keys, URLs and model names: padding and quotes stripped; a pasted key with a trailing space breaks every call."""
        if isinstance(value, str) and info.field_name is not None and (info.field_name.endswith(("_api_key", "_api_url", "_model")) or info.field_name == "provider"):
            value = value.strip().strip("'\"").strip()
            if value == "":
                raise PydanticUseDefault()
        return value


class GrafeoSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="GRAFEO_", extra="ignore")

    db_dir: str = "workspace/graphs"  # one <repository>.grafeo per repository, in the home folder; empty: in-memory
    db_path: str = ""  # no longer supported; refused when set
    log_queries: bool = False
    slow_query_ms: float = 1000.0


class GraphSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="GRAPH_", extra="ignore")

    namespace: str = "Graph"
    cache_dir: str = "workspace/cache/graph"


class ArchimateSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="ARCHIMATE_", extra="ignore")

    namespace: str = "Model"
    validation_strict_mode: bool = False


class NlpSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="DERIVA_NLP_", extra="ignore")

    models_dir: str = "workspace/cache/nlp"


class RepositorySettings(_Group):
    model_config = SettingsConfigDict(env_prefix="REPOSITORY_", extra="ignore")

    workspace_dir: str = "workspace/repositories"


def model_configs() -> dict[str, dict[str, str | None]]:
    """Named model configs: LLM_{NAME}_PROVIDER with its _MODEL, _URL, _KEY, _KEY_ENV, _SAMPLING, _REASONING, _TEMPERATURE and _CONTEXT (NAME as written)."""
    env = environment()
    configs: dict[str, dict[str, str | None]] = {}
    for key, value in env.items():
        if key.startswith("LLM_") and key.endswith("_PROVIDER") and key != "LLM_PROVIDER":
            name = key[len("LLM_") : -len("_PROVIDER")]
            configs[name] = {
                "provider": value,
                "model": env.get(f"LLM_{name}_MODEL", ""),
                "url": env.get(f"LLM_{name}_URL"),
                "key": env.get(f"LLM_{name}_KEY"),
                "key_env": env.get(f"LLM_{name}_KEY_ENV"),
                "sampling": env.get(f"LLM_{name}_SAMPLING"),
                "reasoning": env.get(f"LLM_{name}_REASONING"),
                "temperature": env.get(f"LLM_{name}_TEMPERATURE"),
                "context": env.get(f"LLM_{name}_CONTEXT"),
            }
    return configs
