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
        {"name": "anthropic-haiku", "provider": "anthropic", "model": "claude-haiku", "url": None, "key": "sk-...abcd", "key_env": None, "structured_output": "tool"},
        {"name": "anthropic-haiku-alt", "provider": "anthropic", "model": "claude-haiku", "url": None, "key": None, "key_env": "OTHER_KEY", "structured_output": None},
    ]
    assert "sk-ant-secret" not in json.dumps(models)


def test_a_new_model_is_written_and_the_rest_of_the_file_kept(env):
    set_model(env, "mistral-small", provider="mistral", model="mistral-small-latest", url="https://api.mistral.example", key="sk-new-key-0000wxyz")

    text = env.read_text(encoding="utf-8")
    assert text.startswith(ENV)
    assert "LLM_MISTRAL_SMALL_MODEL=mistral-small-latest" in text
    added = {m["name"]: m for m in list_models(env)}["mistral-small"]
    assert (added["provider"], added["url"], added["key"]) == ("mistral", "https://api.mistral.example", "sk-...wxyz")


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
    assert "LLM_ANTHROPIC_HAIKU_ALT_PROVIDER=anthropic" in text
    assert "LLM_ANTHROPIC_HAIKU_ALT_KEY_ENV=OTHER_KEY" in text
    assert "# second account" in text
    assert [m["name"] for m in list_models(env)] == ["anthropic-haiku-alt"]


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
