"""Command line: `deriva-nlp models`, `deriva-nlp extract`, `deriva-nlp version` (JSON on stdout or in files)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .extract import extract, tool_versions
from .models import ensure_all
from .settings import Settings


def _models(args: argparse.Namespace) -> None:
    paths = ensure_all(Path(args.models_dir), download=True)
    print(json.dumps({lang: str(path) for lang, path in paths.items()}))


def _extract(args: argparse.Namespace) -> None:
    from .phrases import load_pipelines
    from .translate import load_translators

    request = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = extract(
        request["documents"],
        Settings.from_dict(request.get("settings", {})),
        load_pipelines(),
        load_translators(Path(args.models_dir)),
        frozenset(request.get("keep_surface", [])),
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _version(args: argparse.Namespace) -> None:
    print(json.dumps(tool_versions(), sort_keys=True))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="deriva-nlp", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    models = commands.add_parser("models", help="Download and verify the translation models")
    models.add_argument("--models-dir", required=True)
    models.set_defaults(run=_models)
    run = commands.add_parser("extract", help="Extract candidate terms from documents (JSON in, JSON out)")
    run.add_argument("--input", required=True, help='JSON file: {"documents": [{"path", "text"}], "settings": {...}, "keep_surface": [...]}')
    run.add_argument("--output", required=True)
    run.add_argument("--models-dir", required=True)
    run.set_defaults(run=_extract)
    commands.add_parser("version", help="Versions of the tool and its models").set_defaults(run=_version)
    args = parser.parse_args(argv)
    try:
        args.run(args)
    except (OSError, ValueError) as e:
        print(f"deriva-nlp: {e}", file=sys.stderr)
        raise SystemExit(2) from e


if __name__ == "__main__":
    main()
