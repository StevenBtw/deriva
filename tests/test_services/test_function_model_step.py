"""The function model step: its config, the bundled model file, and the classification of the services into it."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deriva.services import derivation

FIXTURE = Path(__file__).parents[1] / "test_modules" / "derivation" / "data" / "function_model_fixture.csv"


def test_the_config_names_a_model_and_its_file():
    config = derivation._function_model_config(json.dumps({"function_model": {"name": "fixture", "path": str(FIXTURE), "exclude": ["F200"], "batch_size": 5}}))

    assert config is not None and (config.name, config.exclude, config.levels, config.batch_size) == ("fixture", ("F200",), 2, 5)
    assert derivation._function_model_config(json.dumps({"other": 1})) is None


@pytest.mark.parametrize("settings", [{"path": "x.csv"}, {"name": "m"}, {"name": "m", "path": "x.csv", "exclude": "F1"}, {"name": "m", "path": "x.csv", "levels": 3}])
def test_an_incomplete_config_is_an_error(settings):
    with pytest.raises(ValueError, match="function_model"):
        derivation._function_model_config(json.dumps({"function_model": settings}))


def test_the_bundled_pcf_model_reads_and_leaves_out_an_excluded_category():
    from deriva.modules.derivation.function_model import parse_function_model

    text = derivation._function_model_file("pcf-8.0-cross-industry.csv").read_text(encoding="utf-8")
    model = parse_function_model(text, "pcf-8.0", exclude=("20607",))

    assert text.startswith("# ©2026 APQC. ALL RIGHTS RESERVED.")  # the licence notice travels with the file
    assert len(model.level(1)) == 12 and model.get("20607") is None and model.get("20608") is None  # Manage IT and its groups
    assert model.get("10105").name == "Develop and manage sales plans" and model.get("10105").parent == "10004"


def test_a_missing_model_file_is_an_error():
    with pytest.raises(ValueError, match="no function model file"):
        derivation._function_model_file("no-such-model.csv")


class _Graph:
    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "DataDomain" in cypher:
            return [{"id": "domain::r::bid", "bo": "Bid"}, {"id": "domain::r::cache", "bo": None}]
        if "DeployableUnit" in cypher:
            return [{"id": "unit::r::engine", "name": "trading-engine"}, {"id": "unit::r::cache", "name": "cache"}]
        return [{"id": "lifecycle::r::bid", "name": "Bid Lifecycle"}]


class _Store:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add_element(self, element: Any) -> None:
        self.added.append(element)


def test_only_services_that_touch_a_business_domain_are_classified_and_their_functions_stored():
    elements = [
        {"identifier": "do_bid", "name": "Bid Data", "element_type": "DataObject", "properties": {"source": "domain::r::bid"}},
        {"identifier": "do_cache", "name": "Cache Data", "element_type": "DataObject", "properties": {"source": "domain::r::cache"}},
        {
            "identifier": "as_engine",
            "name": "Bid Processing",
            "element_type": "ApplicationService",
            "properties": {"sources": ["unit::r::engine"], "objects": ["do_bid"], "members": [{"name": "BidResource"}], "processes": ["lifecycle::r::bid"]},
        },
        {"identifier": "as_cache", "name": "Cache Management", "element_type": "ApplicationService", "properties": {"sources": ["unit::r::cache"], "objects": ["do_cache"]}},
    ]
    prompts: list[str] = []

    def query(prompt: str, schema: dict[str, Any], **kwargs: Any) -> Any:
        prompts.append(prompt)
        keys = list(schema["schema"]["properties"]["choices"]["properties"])
        return SimpleNamespace(content=json.dumps({"choices": dict.fromkeys(keys, "F100" if "level 1" in prompt else "F110")}))

    config = derivation.FunctionModelConfig(name="fixture", path=str(FIXTURE))
    store = _Store()

    result = derivation._function_model_step(config, "Classify.", _Graph(), store, query, elements)  # type: ignore[arg-type]

    assert result["function_decisions"] == {"as_engine": ("F100", "F110")}  # the cache service touches no business domain
    assert all("cache" not in p for p in prompts) and "trading-engine" in prompts[0] and "Bid Lifecycle" in prompts[0]
    stored = {e.name: e for e in store.added}
    assert set(stored) == {"Run the Trading Floor", "Take bids"}
    assert stored["Take bids"].properties["services"] == ["as_engine"] and stored["Take bids"].properties["processes"] == ["lifecycle::r::bid"]


class _RichGraph:
    """The queries of the richer evidence: units with documentation lines, types, methods with decorators."""

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "DataDomain" in cypher:
            return [{"id": "domain::r::bid", "bo": "Bid"}]
        if "DeployableUnit" in cypher:
            return [
                {"id": "unit::r::engine", "name": "trading-engine", "path": "r/engine"},
                {"id": "unit::r::auth", "name": "auth", "path": "r/auth"},
                {"id": "unit::r::board", "name": "board", "path": "r/board"},
            ]
        if "Lifecycle" in cypher:
            return [{"id": "lifecycle::r::bid", "name": "Bid Lifecycle"}]
        if "CONTAINS" in cypher:
            return [
                {"t": "t::BidResource", "name": "placeBid", "decorators": ['PostMapping(value = "/bids")'], "line": 3},
                {"t": "t::LoginResource", "name": "login", "decorators": ['PostMapping(value = "/login")'], "line": 3},
                {"t": "t::BoardResource", "name": "summary", "decorators": ['GetMapping(value = "/summary")'], "line": 3},
            ]
        if "TypeDefinition" in cypher:
            return [{"id": t, "decorators": []} for t in ("t::BidResource", "t::LoginResource", "t::BoardResource")]
        if "n.id IN" in cypher:  # element_source_paths
            return [{"id": t, "file_path": f"r/{t[3:]}.java"} for t in ("t::BidResource", "t::LoginResource", "t::BoardResource")]
        return []


def test_the_richer_evidence_classifies_services_with_data_or_endpoints_but_not_technical_ones(monkeypatch):
    monkeypatch.setattr(derivation, "_documentation_files", lambda gm: {"r/engine/README.md": "# Engine\n\nThe **trading engine** matches bids.\n"})

    def service(key: str, unit: str, member: str, objects: list[str], states: list[str] | None = None) -> dict[str, Any]:
        props = {"sources": [unit], "objects": objects, "members": [{"name": member, "source": f"t::{member}"}], "interfaces": [f"ai_{key}"], "states": states or []}
        return {"identifier": key, "name": key, "element_type": "ApplicationService", "properties": props}

    elements = [
        {"identifier": "do_bid", "name": "Bid Data", "element_type": "DataObject", "properties": {"source": "domain::r::bid"}},
        {"identifier": "ai_as_engine", "name": "x", "element_type": "ApplicationInterface", "properties": {"role": "rest"}},
        service("as_engine", "unit::r::engine", "BidResource", ["do_bid"], ["lifecycle::r::bid::PLACED"]),
        service("as_auth", "unit::r::auth", "LoginResource", []),
        service("as_board", "unit::r::board", "BoardResource", []),
    ]
    prompts: list[str] = []

    def query(prompt: str, schema: dict[str, Any], **kwargs: Any) -> Any:
        prompts.append(prompt)
        keys = list(schema["schema"]["properties"]["choices"]["properties"])
        return SimpleNamespace(content=json.dumps({"choices": dict.fromkeys(keys, "none")}))

    params = {
        "function_model": {
            "name": "fixture",
            "path": str(FIXTURE),
            "services": "data_or_endpoints",
            "evidence": {"operation_patterns": [r"^(?P<verb>Get|Post)Mapping(?:\(value = \"(?P<path>[^\"]*)\"\))?"], "technical_words": ["login"]},
        }
    }
    config = derivation._function_model_config(json.dumps(params))
    assert config is not None

    result = derivation._function_model_step(config, "Classify.", _RichGraph(), _Store(), query, elements)  # type: ignore[arg-type]

    assert set(result["function_decisions"]) == {"as_engine", "as_board"}  # the login service is technical
    prompt = prompts[0]
    for text in ("POST /bids placeBid", "GET /summary summary", "Bid Lifecycle: PLACED", "interfaces: rest", "The trading engine matches bids."):
        assert text in prompt
