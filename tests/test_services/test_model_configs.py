"""Model configs in .env: listed with masked keys, written in place, deleted by exact keys only."""

from __future__ import annotations

import json

import pytest

from deriva.services.model_configs import delete_model, list_models, set_model

ENV = """# LLM settings
LLM_TEMPERATURE=0.0
LLM_PROVIDER=azure
LLM_ANTHROPIC_HAIKU_PROVIDER=anthropic
LLM_ANTHROPIC_HAIKU_MODEL=claude-haiku
LLM_ANTHROPIC_HAIKU_KEY=sk-ant-secret-1234abcd
LLM_ANTHROPIC_HAIKU_STRUCTURED_OUTPUT=tool
# second account
LLM_ANTHROPIC_HAIKU_ALT_PROVIDER=anthropic
LLM_ANTHROPIC_HAIKU_ALT_MODEL=claude-haiku
LLM_ANTHROPIC_HAIKU_ALT_KEY_ENV=OTHER_KEY
"""


@pytest.fixture
def env(tmp_path):
    path = tmp_path / ".env"
    path.write_text(ENV, encoding="utf-8")
    return path


def test_models_are_listed_with_masked_keys(env):
    models = list_models(env)

    assert models == [
        {
            "name": "anthropic-haiku",
            "provider": "anthropic",
            "model": "claude-haiku",
            "url": None,
            "key": "sk-...abcd",
            "key_env": None,
            "sampling": None,
            "reasoning": None,
            "temperature": None,
            "context": None,
            "default": False,
        },
        {
            "name": "anthropic-haiku-alt",
            "provider": "anthropic",
            "model": "claude-haiku",
            "url": None,
            "key": None,
            "key_env": "OTHER_KEY",
            "sampling": None,
            "reasoning": None,
            "temperature": None,
            "context": None,
            "default": False,
        },
    ]
    assert "sk-ant-secret" not in json.dumps(models)


def test_a_new_model_is_written_and_the_rest_of_the_file_kept(env):
    set_model(env, "mistral-small", provider="mistral", model="mistral-small-latest", url="https://api.mistral.example", key="sk-new-key-0000wxyz")

    text = env.read_text(encoding="utf-8")
    assert text.startswith(ENV)
    assert "LLM_MISTRAL_SMALL_MODEL=mistral-small-latest" in text
    added = {m["name"]: m for m in list_models(env)}["mistral-small"]
    assert (added["provider"], added["url"], added["key"]) == ("mistral", "https://api.mistral.example", "sk-...wxyz")


def test_the_first_model_becomes_the_default(tmp_path):
    """A fresh home: the model saved in General is the one Deriva uses, without an LLM_DEFAULT_MODEL line by hand."""
    path = tmp_path / ".env"
    set_model(path, "mistral-small", provider="mistral", model="mistral-small-latest", key="sk-new-key-0000wxyz")
    set_model(path, "ollama-local", provider="ollama", model="llama3.2")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [line for line in lines if line.startswith("LLM_DEFAULT_MODEL=")] == ["LLM_DEFAULT_MODEL=mistral-small"]


def test_deleting_the_default_model_removes_the_default(tmp_path):
    path = tmp_path / ".env"
    set_model(path, "mistral-small", provider="mistral", model="mistral-small-latest", key="sk-new-key-0000wxyz")

    delete_model(path, "mistral-small")

    assert "LLM_DEFAULT_MODEL" not in path.read_text(encoding="utf-8")


def test_saving_without_a_key_keeps_the_stored_key(env):
    set_model(env, "anthropic-haiku", provider="anthropic", model="claude-haiku-2")

    model = {m["name"]: m for m in list_models(env)}["anthropic-haiku"]
    assert (model["model"], model["key"]) == ("claude-haiku-2", "sk-...abcd")
    assert "LLM_ANTHROPIC_HAIKU_KEY=sk-ant-secret-1234abcd" in env.read_text(encoding="utf-8")


def test_an_empty_url_removes_it(env):
    set_model(env, "anthropic-haiku", provider="anthropic", model="claude-haiku", url="https://a.example")
    set_model(env, "anthropic-haiku", provider="anthropic", model="claude-haiku", url="")

    assert {m["name"]: m for m in list_models(env)}["anthropic-haiku"]["url"] is None


def test_delete_removes_exactly_that_models_keys(env):
    delete_model(env, "anthropic-haiku")

    text = env.read_text(encoding="utf-8")
    assert "LLM_ANTHROPIC_HAIKU_PROVIDER" not in text
    assert "LLM_ANTHROPIC_HAIKU_KEY=" not in text
    # The structured output mode is no longer a model setting; a line left from it goes with its model
    assert "LLM_ANTHROPIC_HAIKU_STRUCTURED_OUTPUT" not in text
    assert "LLM_ANTHROPIC_HAIKU_ALT_PROVIDER=anthropic" in text
    assert "LLM_ANTHROPIC_HAIKU_ALT_KEY_ENV=OTHER_KEY" in text
    assert "# second account" in text
    assert [m["name"] for m in list_models(env)] == ["anthropic-haiku-alt"]


def test_there_is_no_structured_output_setting(env):
    """No code read it (pydantic-ai picks the output mode), so a model config neither lists nor takes it."""
    import inspect

    assert all("structured_output" not in m for m in list_models(env))
    assert "structured_output" not in inspect.signature(set_model).parameters


def test_unknown_providers_names_and_models_are_refused(env):
    with pytest.raises(ValueError):
        set_model(env, "m", provider="nope", model="x")
    with pytest.raises(ValueError):
        set_model(env, "Bad Name", provider="anthropic", model="x")
    with pytest.raises(ValueError):
        set_model(env, "m", provider="anthropic", model="")
    with pytest.raises(KeyError):
        delete_model(env, "missing")
    assert env.read_text(encoding="utf-8") == ENV


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_an_add_and_delete_round_trip_leaves_the_file_byte_for_byte(tmp_path, newline):
    path = tmp_path / ".env"
    original = ENV.replace("\n", newline).encode("utf-8")
    path.write_bytes(original)

    set_model(path, "mistral-small", provider="mistral", model="mistral-small-latest", key="sk-new-key-0000wxyz")
    changed = path.read_bytes()
    delete_model(path, "mistral-small")

    assert changed.count(b"\r\n") == (changed.count(b"\n") if newline == "\r\n" else 0)
    assert path.read_bytes() == original


def test_changing_a_value_keeps_the_other_lines_byte_for_byte(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(ENV.encode("utf-8"))

    set_model(path, "anthropic-haiku", provider="anthropic", model="claude-haiku-2")

    assert path.read_bytes() == ENV.replace("LLM_ANTHROPIC_HAIKU_MODEL=claude-haiku\n", "LLM_ANTHROPIC_HAIKU_MODEL=claude-haiku-2\n").encode("utf-8")


def test_sampling_and_reasoning_are_saved_and_removed(env):
    set_model(env, "anthropic-haiku55", provider="anthropic", model="claude-haiku-5-5", sampling="false", reasoning="none")

    text = env.read_text(encoding="utf-8")
    assert "LLM_ANTHROPIC_HAIKU55_SAMPLING=false\n" in text and "LLM_ANTHROPIC_HAIKU55_REASONING=none\n" in text
    (saved,) = [m for m in list_models(env) if m["name"] == "anthropic-haiku55"]
    assert (saved["sampling"], saved["reasoning"]) == ("false", "none")

    set_model(env, "anthropic-haiku55", provider="anthropic", model="claude-haiku-5-5", sampling="", reasoning="")
    assert "HAIKU55_SAMPLING" not in env.read_text(encoding="utf-8") and "HAIKU55_REASONING" not in env.read_text(encoding="utf-8")


def test_unusable_sampling_and_reasoning_values_are_refused(env):
    with pytest.raises(ValueError, match="sampling"):
        set_model(env, "x", provider="anthropic", model="claude-haiku-5-5", sampling="sometimes")
    with pytest.raises(ValueError, match="reasoning"):
        set_model(env, "x", provider="anthropic", model="claude-haiku-5-5", reasoning="extreme")
    with pytest.raises(ValueError, match="mistral"):
        set_model(env, "x", provider="mistral", model="mistral-small-2603", reasoning="none")


def test_a_key_written_twice_is_changed_on_every_line(tmp_path):
    """The reader takes a key's last line: changing only the first would change nothing."""
    from dotenv import dotenv_values

    path = tmp_path / ".env"
    path.write_text("LLM_M_PROVIDER=openai\nLLM_M_MODEL=old-1\n# again\nLLM_M_PROVIDER=openai\nLLM_M_MODEL=old-2\n", encoding="utf-8")

    set_model(path, "m", provider="openai", model="new")

    assert dotenv_values(path)["LLM_M_MODEL"] == "new"
    assert path.read_text(encoding="utf-8").count("LLM_M_MODEL=new") == 2


def test_the_default_model_is_set_and_marked(env):
    from dotenv import dotenv_values

    from deriva.services.model_configs import set_default

    set_default(env, "anthropic-haiku-alt")
    set_default(env, "anthropic-haiku")

    assert dotenv_values(env)["LLM_DEFAULT_MODEL"] == "anthropic-haiku"
    assert env.read_text(encoding="utf-8").count("LLM_DEFAULT_MODEL=") == 1
    assert {m["name"]: m["default"] for m in list_models(env)} == {"anthropic-haiku": True, "anthropic-haiku-alt": False}


def test_only_a_configured_model_can_be_the_default(env):
    from deriva.services.model_configs import set_default

    with pytest.raises(KeyError):
        set_default(env, "mistral-small")


def test_a_name_that_is_no_model_name_deletes_nothing(env):
    with pytest.raises(KeyError):
        delete_model(env, "anthropic_haiku")  # would map to anthropic-haiku's keys

    assert "LLM_ANTHROPIC_HAIKU_PROVIDER" in env.read_text(encoding="utf-8")


def test_values_with_line_breaks_are_refused(env):
    """A line break in a value would start another assignment in .env (another model's key or URL)."""
    before = env.read_bytes()

    for field in ("model", "url", "key", "key_env", "sampling"):
        values = {"provider": "openai", "model": "gpt", field: "x\nLLM_ANTHROPIC_HAIKU_URL=http://elsewhere"}
        with pytest.raises(ValueError, match="line break"):
            set_model(env, "openai-x", **values)

    assert env.read_bytes() == before


def test_a_write_that_breaks_off_leaves_the_file_as_it_was(env, monkeypatch):
    """The new file is written next to .env and moved into place: a failed write loses no keys."""
    import os

    before = env.read_bytes()

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        set_model(env, "openai-x", provider="openai", model="gpt")

    assert env.read_bytes() == before
    assert [p.name for p in env.parent.iterdir()] == [".env"]


def test_an_inline_comment_stays_when_the_value_changes(tmp_path):
    path = tmp_path / ".env"
    path.write_text("LLM_A_PROVIDER=openai\nLLM_A_MODEL=old # deployment note\nLLM_A_URL='http://x' # quoted\n", encoding="utf-8")

    set_model(path, "a", provider="openai", model="new", url="http://y")

    text = path.read_text(encoding="utf-8")
    assert "LLM_A_MODEL=new # deployment note\n" in text
    assert "LLM_A_URL=http://y # quoted\n" in text
    (saved,) = list_models(path)
    assert (saved["model"], saved["url"]) == ("new", "http://y")


def test_a_name_in_another_spelling_cannot_be_the_default(env):
    """anthropic_haiku maps onto the same variables, but the model is known as anthropic-haiku only."""
    from deriva.services.model_configs import set_default

    with pytest.raises(KeyError):
        set_default(env, "anthropic_haiku")


def test_deleting_the_default_model_removes_a_quoted_or_commented_default(tmp_path):
    path = tmp_path / ".env"
    set_model(path, "mistral-small", provider="mistral", model="mistral-small-latest", key="sk-new-key-0000wxyz")
    text = path.read_text(encoding="utf-8").replace("LLM_DEFAULT_MODEL=mistral-small", 'LLM_DEFAULT_MODEL="mistral-small"  # the one we use')
    path.write_text(text, encoding="utf-8")

    delete_model(path, "mistral-small")

    assert "LLM_DEFAULT_MODEL" not in path.read_text(encoding="utf-8")


def test_a_model_context_is_saved_listed_and_removed(env):
    set_model(env, "ollama-qwen", provider="ollama", model="qwen3:8b", context="8192")

    assert "LLM_OLLAMA_QWEN_CONTEXT=8192\n" in env.read_text(encoding="utf-8")
    (saved,) = [m for m in list_models(env) if m["name"] == "ollama-qwen"]
    assert saved["context"] == "8192"
    for wrong in ("big", "0", "-1", "1.5"):
        with pytest.raises(ValueError, match="context"):
            set_model(env, "ollama-qwen", provider="ollama", model="qwen3:8b", context=wrong)
    set_model(env, "ollama-qwen", provider="ollama", model="qwen3:8b", context="")
    assert "QWEN_CONTEXT" not in env.read_text(encoding="utf-8")


def test_a_model_temperature_is_saved_listed_and_removed(env):
    set_model(env, "mistral-small4", provider="mistral", model="mistral-small-2603", temperature="0")

    assert "LLM_MISTRAL_SMALL4_TEMPERATURE=0\n" in env.read_text(encoding="utf-8")
    (saved,) = [m for m in list_models(env) if m["name"] == "mistral-small4"]
    assert saved["temperature"] == "0"
    with pytest.raises(ValueError, match="temperature"):
        set_model(env, "mistral-small4", provider="mistral", model="mistral-small-2603", temperature="cold")
    set_model(env, "mistral-small4", provider="mistral", model="mistral-small-2603", temperature="")
    assert "SMALL4_TEMPERATURE" not in env.read_text(encoding="utf-8")
