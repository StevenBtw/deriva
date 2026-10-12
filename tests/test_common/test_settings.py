"""One settings layer: the home .env merged under the process environment."""

from __future__ import annotations

import os

import pytest

from deriva.common import settings
from deriva.common.settings import ArchimateSettings, GrafeoSettings, GraphSettings, LlmSettings, NlpSettings, RepositorySettings, model_configs


@pytest.fixture
def dotenv(monkeypatch, tmp_path):
    """Point the settings at a temporary .env and return a writer for it."""
    path = tmp_path / ".env"
    monkeypatch.setattr(settings, "env_file", lambda: path)
    last = [0]

    def write(text: str) -> None:
        path.write_text(text, encoding="utf-8")
        # Each write gets a later modification time than the one before, also on coarse clocks
        last[0] = max(last[0], path.stat().st_mtime_ns) + 1_000_000
        os.utime(path, ns=(last[0], last[0]))

    return write


def test_tests_never_read_the_developers_env_file():
    assert not settings.env_file().exists()
    assert settings.read_env_file() == {}


def test_the_file_is_read_and_the_environment_wins(dotenv, monkeypatch):
    dotenv("DERIVA_TEST_A=file\nDERIVA_TEST_B=file\n")
    monkeypatch.setenv("DERIVA_TEST_B", "process")

    env = settings.environment()

    assert (env["DERIVA_TEST_A"], env["DERIVA_TEST_B"]) == ("file", "process")
    assert settings.get("DERIVA_TEST_B") == "process"
    assert settings.get("DERIVA_TEST_MISSING", "fallback") == "fallback"


def test_an_empty_process_value_still_wins(dotenv, monkeypatch):
    dotenv("DERIVA_TEST_DIR=workspace/graphs\n")
    monkeypatch.setenv("DERIVA_TEST_DIR", "")

    assert settings.get("DERIVA_TEST_DIR") == ""


def test_a_changed_file_is_read_again(dotenv):
    dotenv("DERIVA_TEST_MODEL=one\n")
    assert settings.get("DERIVA_TEST_MODEL") == "one"

    dotenv("DERIVA_TEST_MODEL=two\n")
    assert settings.get("DERIVA_TEST_MODEL") == "two"


def test_comments_quotes_and_keys_without_values(dotenv):
    dotenv("A_DELAY=2.0      # seconds\nA_FLAG='true'\nA_EMPTY=\nA_BARE\n")

    env = settings.read_env_file()

    assert (env["A_DELAY"], env["A_FLAG"], env["A_EMPTY"]) == ("2.0", "true", "")
    assert "A_BARE" not in env


def test_reading_never_changes_the_process_environment(dotenv):
    dotenv("DERIVA_TEST_ONLY_IN_FILE=x\n")
    settings.environment()

    assert "DERIVA_TEST_ONLY_IN_FILE" not in os.environ


def test_defaults_are_todays_literals(dotenv, monkeypatch):
    for name in list(os.environ):
        if name.startswith(("LLM_", "GRAFEO_", "GRAPH_", "ARCHIMATE_", "DERIVA_NLP_", "REPOSITORY_")):
            monkeypatch.delenv(name)
    dotenv("")

    llm = LlmSettings()
    assert (llm.default_model, llm.provider, llm.temperature, llm.max_retries, llm.timeout, llm.max_tokens) == (None, "azure", 0.7, 3, 60, None)
    assert (llm.cache_dir, llm.cache_ttl, llm.nocache) == ("workspace/cache/llm", 0, False)
    assert (llm.rate_limit_rpm, llm.rate_limit_delay, llm.retry_base_delay, llm.retry_max_delay) == (0, 0.0, 2.0, 60.0)
    assert (llm.throttle_enabled, llm.throttle_min_factor, llm.throttle_recovery_time) == (True, 0.25, 60.0)
    assert (llm.circuit_breaker_enabled, llm.circuit_failure_threshold, llm.circuit_recovery_time) == (True, 5, 30.0)
    assert (llm.azure_api_url, llm.azure_api_key, llm.azure_model) == (None, None, "gpt-4o-mini")
    assert (llm.openai_api_key, llm.openai_model, llm.anthropic_api_key, llm.anthropic_model) == (None, "gpt-4o-mini", None, "claude-sonnet-4-20250514")
    assert (llm.ollama_api_url, llm.ollama_model) == ("http://localhost:11434/api/chat", "llama3.2")
    assert (llm.mistral_api_key, llm.mistral_model) == (None, "mistral-large-latest")
    assert (llm.lmstudio_api_url, llm.lmstudio_model) == ("http://localhost:1234/v1/chat/completions", "local-model")
    grafeo = GrafeoSettings()
    # Graphs persist in the home folder unless GRAFEO_DB_DIR is set empty (in-memory)
    assert (grafeo.db_dir, grafeo.db_path, grafeo.log_queries, grafeo.slow_query_ms) == ("workspace/graphs", "", False, 1000.0)
    assert (GraphSettings().namespace, GraphSettings().cache_dir) == ("Graph", "workspace/cache/graph")
    assert (ArchimateSettings().namespace, ArchimateSettings().validation_strict_mode) == ("Model", False)
    assert NlpSettings().models_dir == "workspace/cache/nlp"
    assert RepositorySettings().workspace_dir == "workspace/repositories"
    assert model_configs() == {}


def test_values_come_from_the_file_and_the_environment_wins(dotenv, monkeypatch):
    dotenv("LLM_TEMPERATURE=0.6\nLLM_TIMEOUT=30\nGRAFEO_DB_DIR=workspace/graphs\n")
    monkeypatch.setenv("LLM_TIMEOUT", "90")
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)

    assert (LlmSettings().temperature, LlmSettings().timeout) == (0.6, 90)
    assert GrafeoSettings().db_dir == ""  # the test environment's explicit empty value wins (conftest)


def test_empty_values_padding_and_quotes(dotenv, monkeypatch):
    for name in ("LLM_MAX_TOKENS", "LLM_RETRY_BASE_DELAY", "LLM_NOCACHE", "LLM_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    dotenv("LLM_MAX_TOKENS=\nLLM_RETRY_BASE_DELAY=2.5      # seconds\nLLM_NOCACHE='true'\nLLM_TIMEOUT=\n")

    llm = LlmSettings()

    assert (llm.max_tokens, llm.retry_base_delay, llm.nocache, llm.timeout) == (None, 2.5, True, 60)


def test_booleans_accept_the_usual_words_and_refuse_others(dotenv, monkeypatch):
    monkeypatch.setenv("LLM_THROTTLE_ENABLED", "0")
    assert LlmSettings().throttle_enabled is False
    monkeypatch.setenv("LLM_THROTTLE_ENABLED", "yes")
    assert LlmSettings().throttle_enabled is True
    monkeypatch.setenv("LLM_THROTTLE_ENABLED", "maybe")
    with pytest.raises(ValueError):
        LlmSettings()


def test_named_model_configs(dotenv, monkeypatch):
    for name in [n for n in os.environ if n.startswith("LLM_")]:
        monkeypatch.delenv(name)
    dotenv("LLM_PROVIDER=azure\nLLM_MISTRAL_DEVSTRAL_PROVIDER=mistral\nLLM_MISTRAL_DEVSTRAL_MODEL=devstral-2512\nLLM_MISTRAL_DEVSTRAL_KEY=sk-1\n")
    monkeypatch.setenv("LLM_LOCAL_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_LOCAL_MODEL", "llama3.2")
    monkeypatch.setenv("LLM_LOCAL_URL", "http://localhost:11434/api/chat")

    configs = model_configs()

    assert set(configs) == {"MISTRAL_DEVSTRAL", "LOCAL"}
    assert configs["MISTRAL_DEVSTRAL"] == {"provider": "mistral", "model": "devstral-2512", "url": None, "key": "sk-1", "key_env": None, "sampling": None, "reasoning": None}
    assert configs["LOCAL"]["url"] == "http://localhost:11434/api/chat"


def test_provider_keys_reach_the_llm_libraries(dotenv, monkeypatch):
    """pydantic-ai's providers read only os.environ; the provider variables from .env are handed over, nothing else."""
    for name in ("MISTRAL_API_KEY", "OPENAI_API_KEY", "PYPI_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "_ORIGINAL_ENVIRONMENT", frozenset({"OPENAI_API_KEY"}))
    monkeypatch.setattr(settings, "_EXPORTED", set())
    monkeypatch.setenv("OPENAI_API_KEY", "sk-process")
    dotenv("MISTRAL_API_KEY=sk-file\nOPENAI_API_KEY=sk-file-openai\nPYPI_TOKEN=secret\n")

    settings.export_provider_keys()

    assert os.environ["MISTRAL_API_KEY"] == "sk-file"
    assert os.environ["OPENAI_API_KEY"] == "sk-process"  # the process's own value wins
    assert "PYPI_TOKEN" not in os.environ  # only the provider variables are handed over


def test_a_saved_provider_key_applies_to_the_next_export(dotenv, monkeypatch):
    monkeypatch.setattr(settings, "_ORIGINAL_ENVIRONMENT", settings._ORIGINAL_ENVIRONMENT - {"MISTRAL_API_KEY"})
    monkeypatch.setattr(settings, "_EXPORTED", set())
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

    dotenv("MISTRAL_API_KEY=one\n")
    settings.export_provider_keys()
    dotenv("MISTRAL_API_KEY=two\n")
    settings.export_provider_keys()

    assert os.environ["MISTRAL_API_KEY"] == "two"


def test_model_configs_carry_sampling_and_reasoning(dotenv, monkeypatch):
    dotenv("LLM_HAIKU_PROVIDER=anthropic\nLLM_HAIKU_MODEL=claude-haiku-5-5\nLLM_HAIKU_SAMPLING=false\nLLM_HAIKU_REASONING=none\n")

    assert {k: model_configs()["HAIKU"][k] for k in ("sampling", "reasoning")} == {"sampling": "false", "reasoning": "none"}


def test_a_provider_key_removed_from_the_file_leaves_the_process(dotenv, monkeypatch):
    monkeypatch.setattr(settings, "_ORIGINAL_ENVIRONMENT", settings._ORIGINAL_ENVIRONMENT - {"MISTRAL_API_KEY"})
    monkeypatch.setattr(settings, "_EXPORTED", set())
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

    dotenv("MISTRAL_API_KEY=one\n")
    settings.export_provider_keys()
    dotenv("OTHER=1\n")
    settings.export_provider_keys()

    assert "MISTRAL_API_KEY" not in os.environ


def test_llm_credentials_are_stripped(dotenv, monkeypatch):
    for name in list(os.environ):
        if name.startswith("LLM_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("LLM_PROVIDER", " openai ")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", " anthropic ")
    monkeypatch.setenv("LLM_ANTHROPIC_API_KEY", "  sk-ant-123  ")
    monkeypatch.setenv("LLM_ANTHROPIC_MODEL", " claude-sonnet-4-20250514 ")
    monkeypatch.setenv("LLM_OLLAMA_API_URL", " http://localhost:11434/api/chat ")

    llm = LlmSettings()

    assert (llm.provider, llm.default_model) == ("openai", "anthropic")
    assert llm.anthropic_api_key == "sk-ant-123"
    assert llm.anthropic_model == "claude-sonnet-4-20250514"
    assert llm.ollama_api_url == "http://localhost:11434/api/chat"


def test_llm_credentials_strip_padding_inside_quotes(dotenv, monkeypatch):
    """Padding inside quotes goes too: '  sk-ant-123  ' comes out clean."""
    for name in list(os.environ):
        if name.startswith("LLM_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("LLM_PROVIDER", "' openai '")
    monkeypatch.setenv("LLM_ANTHROPIC_API_KEY", '"  sk-ant-123  "')
    monkeypatch.setenv("LLM_ANTHROPIC_MODEL", "' claude-sonnet-4-20250514 '")

    llm = LlmSettings()

    assert llm.provider == "openai"
    assert llm.anthropic_api_key == "sk-ant-123"
    assert llm.anthropic_model == "claude-sonnet-4-20250514"
