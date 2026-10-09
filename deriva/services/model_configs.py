"""LLM model configs in ``.env``: list them with masked keys, add or change one, delete one.

A model ``name`` (``anthropic-haiku``) lives in ``LLM_{NAME}_PROVIDER``, ``_MODEL``, ``_URL``,
``_KEY``, ``_KEY_ENV`` and ``_STRUCTURED_OUTPUT`` (``NAME`` = upper case, ``-`` as ``_``), the
format the benchmark reads. Writes edit only the lines of these keys and keep every other byte
of the file (comments, order, the file's own line endings); a delete removes exactly these
keys, so a model whose name extends another (``anthropic-haiku-alt``) is never touched. Keys
are returned masked only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, find_dotenv

from deriva.adapters.llm.model_registry import VALID_PROVIDERS

FIELDS = ("PROVIDER", "MODEL", "URL", "KEY", "KEY_ENV", "STRUCTURED_OUTPUT")
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
PROVIDER_KEY = re.compile(r"LLM_(?P<name>[A-Z0-9_]+)_PROVIDER")
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def default_env_path() -> Path:
    """The .env of the working directory (or the nearest parent with one)."""
    return Path(find_dotenv(usecwd=True) or ".env")


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


def _set(lines: list[str], newline: str, key: str, value: str) -> None:
    """Replace the value on the key's line (keeping its prefix and line ending), or append the key."""
    for i, line in enumerate(lines):
        match = ASSIGNMENT.match(line)
        if match and match.group(1) == key:
            body = line.rstrip("\r\n")
            lines[i] = f"{body[: match.end(1)]}={value}{line[len(body) :]}"
            return
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    lines.append(f"{key}={value}{newline}")


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("".join(lines), encoding="utf-8", newline="")


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
                "structured_output": field["STRUCTURED_OUTPUT"],
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
    structured_output: str | None = None,
) -> None:
    """Add or change a model config; ``None`` keeps a field, ``""`` removes it (a blank key keeps the stored key)."""
    if not NAME.fullmatch(name):
        raise ValueError(f"Model names use lower case letters, digits and '-': {name!r}")
    if provider.lower() not in VALID_PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}; one of {', '.join(sorted(VALID_PROVIDERS))}")
    if not model.strip():
        raise ValueError("A model id is required")
    env = _env_name(name)
    path = Path(env_path)
    lines, newline = _read_lines(path)
    _set(lines, newline, f"LLM_{env}_PROVIDER", provider.lower())
    _set(lines, newline, f"LLM_{env}_MODEL", model.strip())
    for field, value in (("URL", url), ("KEY", key or None), ("KEY_ENV", key_env), ("STRUCTURED_OUTPUT", structured_output)):
        variable = f"LLM_{env}_{field}"
        if value is None:
            continue
        if value == "":
            lines = [line for line in lines if _key_of(line) != variable]
        else:
            _set(lines, newline, variable, value)
    _write(path, lines)


def delete_model(env_path: str | Path, name: str) -> None:
    """Remove the model's keys (exact names only)."""
    env = _env_name(name)
    path = Path(env_path)
    lines, _ = _read_lines(path)
    if f"LLM_{env}_PROVIDER" not in {_key_of(line) for line in lines}:
        raise KeyError(f"No model config named {name!r}")
    variables = {f"LLM_{env}_{field}" for field in FIELDS}
    _write(path, [line for line in lines if _key_of(line) not in variables])
