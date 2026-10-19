"""LLM model configs in ``.env``: list them with masked keys, add or change one, delete one.

A model ``name`` (``anthropic-haiku``) lives in ``LLM_{NAME}_PROVIDER``, ``_MODEL``, ``_URL``,
``_KEY``, ``_KEY_ENV``, ``_SAMPLING`` and ``_REASONING`` (``NAME`` = upper case, ``-`` as ``_``), the
format the benchmark reads. Writes edit only the lines of these keys and keep every other byte
of the file (comments, order, the file's own line endings); a delete removes exactly these
keys, so a model whose name extends another (``anthropic-haiku-alt``) is never touched. Keys
are returned masked only.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from deriva.adapters.llm import LLMManager
from deriva.adapters.llm.manager import load_benchmark_models
from deriva.adapters.llm.model_registry import VALID_PROVIDERS, parse_sampling, reasoning_settings
from deriva.adapters.llm.models import FailedResponse
from deriva.common.exceptions import ConfigurationError
from deriva.common.paths import env_file

FIELDS = ("PROVIDER", "MODEL", "URL", "KEY", "KEY_ENV", "SAMPLING", "REASONING", "TEMPERATURE", "CONTEXT")
# Keys of settings Deriva no longer has (no code read them): a delete still removes them with their model
LEGACY_FIELDS = ("STRUCTURED_OUTPUT",)
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
PROVIDER_KEY = re.compile(r"LLM_(?P<name>[A-Z0-9_]+)_PROVIDER")
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
# The .env reader ends a quoted value at its closing quote, an unquoted one at whitespace and '#'
QUOTED = re.compile(r"""\s*(?:'(?:\\'|[^'])*'|"(?:\\"|[^"])*")""")
DEFAULT_MODEL = "LLM_DEFAULT_MODEL"


def default_env_path() -> Path:
    """The .env in the Deriva home folder (the repository root in a checkout)."""
    return env_file()


def _env_name(name: str) -> str:
    return name.upper().replace("-", "_")


def mask(key: str | None) -> str | None:
    """``sk-...4f2a``: enough to recognise a key, never enough to use it."""
    if not key:
        return None
    return f"{key[:3]}...{key[-4:]}" if len(key) >= 12 else "****"


def _read_lines(path: Path) -> tuple[list[str], str]:
    """The file's lines with their own endings, and the newline that new lines get."""
    text = path.read_text(encoding="utf-8", newline="") if path.exists() else ""
    return text.splitlines(keepends=True), "\r\n" if "\r\n" in text else "\n"


def _key_of(line: str) -> str | None:
    match = ASSIGNMENT.match(line)
    return match.group(1) if match else None


def _comment(value: str) -> str:
    """The comment after a value (`` # note``), from where the .env reader ends the value."""
    quoted = QUOTED.match(value)
    match = re.match(r"[ \t]*#.*", value[quoted.end() :]) if quoted else re.search(r"\s+#.*", value)
    return match.group(0) if match else ""


def _set(lines: list[str], newline: str, key: str, value: str) -> None:
    """Replace the value on the key's lines (keeping their prefix, inline comment and line ending), or append the key.

    A key written twice is changed on every line: the reader takes the last one.
    """
    found = False
    for i, line in enumerate(lines):
        match = ASSIGNMENT.match(line)
        if match and match.group(1) == key:
            body = line.rstrip("\r\n")
            lines[i] = f"{body[: match.end(1)]}={value}{_comment(body[match.end() :])}{line[len(body) :]}"
            found = True
    if found:
        return
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    lines.append(f"{key}={value}{newline}")


def _write(path: Path, lines: list[str]) -> None:
    """Write the file next to it and move it into place: a write that breaks off leaves the old file whole."""
    path = path.resolve()  # a linked .env keeps its link: the file it points to is replaced
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as out:
            out.write("".join(lines))
        if path.exists():
            shutil.copymode(path, temp)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def list_models(env_path: str | Path) -> list[dict[str, Any]]:
    """Every model config in the file, by name, with its key masked."""
    values = dotenv_values(env_path)
    models = []
    for key in values:
        match = PROVIDER_KEY.fullmatch(key)
        if not match:
            continue
        env = match["name"]
        field = {f: values.get(f"LLM_{env}_{f}") or None for f in FIELDS}
        models.append(
            {
                "name": env.lower().replace("_", "-"),
                "provider": (field["PROVIDER"] or "").lower(),
                "model": field["MODEL"],
                "url": field["URL"],
                "key": mask(field["KEY"]),
                "key_env": field["KEY_ENV"],
                "sampling": field["SAMPLING"],
                "reasoning": field["REASONING"],
                "temperature": field["TEMPERATURE"],
                "context": field["CONTEXT"],
                "default": values.get(DEFAULT_MODEL) == env.lower().replace("_", "-"),
            }
        )
    return sorted(models, key=lambda m: m["name"])


def set_model(
    env_path: str | Path,
    name: str,
    *,
    provider: str,
    model: str,
    url: str | None = None,
    key: str | None = None,
    key_env: str | None = None,
    sampling: str | None = None,
    reasoning: str | None = None,
    temperature: str | None = None,
    context: str | None = None,
) -> None:
    """Add or change a model config; ``None`` keeps a field, ``""`` removes it (a blank key keeps the stored key).

    ``sampling`` ``false`` is for models that take no temperature; ``reasoning`` is a level
    (``none`` turns reasoning off) for OpenAI, Azure and Anthropic models; ``context`` is the model's context size in
    tokens (a local server's window), so a call that fills it is warned.
    """
    if not NAME.fullmatch(name):
        raise ValueError(f"Model names use lower case letters, digits and '-': {name!r}")
    if provider.lower() not in VALID_PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}; one of {', '.join(sorted(VALID_PROVIDERS))}")
    if not model.strip():
        raise ValueError("A model id is required")
    # A line break would start another assignment in the file (another model's key or URL)
    for field, value in (
        ("model", model),
        ("url", url),
        ("key", key),
        ("key_env", key_env),
        ("sampling", sampling),
        ("reasoning", reasoning),
        ("temperature", temperature),
        ("context", context),
    ):
        if value and any(c in value for c in "\r\n\0"):
            raise ValueError(f"The {field} cannot hold a line break")
    if sampling:
        parse_sampling(sampling)
    if reasoning:
        reasoning_settings(provider.lower(), reasoning.strip().lower())
    if temperature:
        try:
            degrees = float(temperature)
        except ValueError:
            degrees = -1.0
        if not 0.0 <= degrees <= 2.0:
            raise ValueError(f"temperature must be a number between 0 and 2, got {temperature!r}")
    if context and not (context.strip().isdigit() and int(context) > 0):
        raise ValueError(f"context must be a positive whole number of tokens, got {context!r}")
    env = _env_name(name)
    path = Path(env_path)
    lines, newline = _read_lines(path)
    _set(lines, newline, f"LLM_{env}_PROVIDER", provider.lower())
    _set(lines, newline, f"LLM_{env}_MODEL", model.strip())
    for field, value in (
        ("URL", url),
        ("KEY", key or None),
        ("KEY_ENV", key_env),
        ("SAMPLING", sampling.strip().lower() if sampling else sampling),
        ("REASONING", reasoning.strip().lower() if reasoning else reasoning),
        ("TEMPERATURE", temperature.strip() if temperature else temperature),
        ("CONTEXT", context.strip() if context else context),
    ):
        variable = f"LLM_{env}_{field}"
        if value is None:
            continue
        if value == "":
            lines = [line for line in lines if _key_of(line) != variable]
        else:
            _set(lines, newline, variable, value)
    # The first model of a file is the one Deriva uses until another default is chosen
    keys = {_key_of(line) for line in lines}
    others = {match["name"] for key in keys if key and (match := PROVIDER_KEY.fullmatch(key))} - {env}
    if DEFAULT_MODEL not in keys and not others:
        _set(lines, newline, DEFAULT_MODEL, name)
    _write(path, lines)


def set_default(env_path: str | Path, name: str) -> None:
    """Make a configured model the one Deriva uses (``LLM_DEFAULT_MODEL``)."""
    path = Path(env_path)
    lines, newline = _read_lines(path)
    if not NAME.fullmatch(name) or f"LLM_{_env_name(name)}_PROVIDER" not in {_key_of(line) for line in lines}:
        raise KeyError(f"No model config named {name!r}")
    _set(lines, newline, DEFAULT_MODEL, name)
    _write(path, lines)


def delete_model(env_path: str | Path, name: str) -> None:
    """Remove the model's keys (exact names only)."""
    if not NAME.fullmatch(name):
        raise KeyError(f"No model config named {name!r}")
    env = _env_name(name)
    path = Path(env_path)
    lines, _ = _read_lines(path)
    if f"LLM_{env}_PROVIDER" not in {_key_of(line) for line in lines}:
        raise KeyError(f"No model config named {name!r}")
    variables = {f"LLM_{env}_{field}" for field in FIELDS + LEGACY_FIELDS}
    # A default that names this model would point at nothing
    # The parsed value: quotes and a trailing comment are valid in the file
    is_default = dotenv_values(path).get(DEFAULT_MODEL) == name
    kept = [line for line in lines if _key_of(line) not in variables and not (is_default and _key_of(line) == DEFAULT_MODEL)]
    _write(path, kept)


# A connectivity check, not pipeline configuration: it is in no run, no cache and no event log
PROBE = "Reply with the single word OK."
PROBE_TIMEOUT = 30

# What a failed call means for the user: (pattern in the error text or type, sentence)
_MODEL_ERRORS: list[tuple[str, str]] = [
    (r"\b401\b|unauthori[sz]ed|invalid.{0,20}(api )?key|incorrect api key|authentication", "The provider refused the API key: check the key, or the variable it comes from"),
    (r"\b403\b|forbidden|permission", "The API key has no access to model {model}"),
    (
        r"\b404\b|not.found|does not exist|model_not_found|unknown model|invalid.model",
        "The provider does not know the model id {model}: check its spelling and that it is not retired",
    ),
    (r"\b429\b|rate.limit|quota|too many requests", "The provider is limiting this key right now (rate limit or quota): try again later"),
    (r"timeout|timed out", "No answer within " + str(PROBE_TIMEOUT) + " seconds: the provider or the server may be busy"),
    (r"connect|connection|getaddrinfo|name or service not known|refused|unreachable", "Could not reach {url}: is the server running, and is the URL right?"),
]


def _explain(error: str, error_type: str, model: str, url: str) -> str:
    text = f"{error_type} {error}"
    for pattern, sentence in _MODEL_ERRORS:
        if re.search(pattern, text, re.IGNORECASE):
            return sentence.format(model=model, url=url)
    return "The call failed"


def check_model(name: str) -> dict[str, Any]:
    """One small call with a model config (no cache, no retries): whether its key, model id and URL work, with the
    latency and the model that served it, or what to fix.

    Raises:
        KeyError: no model config of that name
    """
    config = load_benchmark_models()[name]
    url = config.get_api_url() or config.provider
    base = {"model": name, "provider": config.provider, "model_id": config.model}
    try:
        manager = LLMManager.from_config(config, nocache=True, max_retries=0, timeout=PROBE_TIMEOUT)
    except ConfigurationError as e:
        return {**base, "ok": False, "error": f"The model config is incomplete: {e}", "detail": str(e)}
    # The answer says what failed: the manager's own warning would repeat it on the console
    manager_log = logging.getLogger("deriva.adapters.llm.manager")
    level = manager_log.level
    manager_log.setLevel(logging.ERROR)
    try:
        response = manager.query(PROBE, use_cache=False)
    finally:
        manager_log.setLevel(level)
    call = manager.last_call or {}
    if isinstance(response, FailedResponse):
        detail = response.error
        return {**base, "ok": False, "error": f"{_explain(detail, response.error_type, config.model, url)} ({response.error_type})", "detail": detail}
    content = str(getattr(response, "content", response))
    return {**base, "ok": True, "served_model": call.get("served_model"), "latency_ms": call.get("latency_ms"), "answer": content.strip()[:80]}
