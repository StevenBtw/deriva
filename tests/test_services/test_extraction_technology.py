"""The Technology step: input files -> items and platforms from structure -> closed classification -> technologies."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deriva.adapters.grafeo.manager import close_database
from deriva.adapters.graph import GraphManager
from deriva.adapters.graph.models import FileNode, TechnologyNode
from deriva.modules.extraction.base import generate_file_node_id
from deriva.services import extraction as service

PLATFORMS = [{"file_type": "dependency", "subtype": "javascript", "name": "Runtime Js", "category": "platform"}]
PARAMS = {"confidence": 0.9, "missing_retries": 1, "platforms": PLATFORMS}
PACKAGE = json.dumps({"dependencies": {"alpha-client": "1", "beta-lib": "2"}})


class FakeLlm:
    """Labels the prompted items from a table (text -> category, system); `skip` items are left out of the first answer."""

    def __init__(self, labels, skip=(), response=None):
        self.labels = labels
        self.skip = set(skip)
        self.response = response
        self.calls = []

    def __call__(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        if self.response is not None:
            return self.response
        texts = re.findall(r'^\d+\. "([^"]+)"', prompt, re.MULTILINE)
        answer = []
        for text in texts:
            if len(self.calls) == 1 and text in self.skip:
                continue
            category, system = self.labels.get(text, ("none", ""))
            answer.append({"item": text, "category": category, "system": system})
        return SimpleNamespace(content=json.dumps({"items": answer}))

    def prompted_items(self, call):
        return re.findall(r'^\d+\. "([^"]+)"', self.calls[call]["prompt"], re.MULTILINE)


@pytest.fixture
def graph():
    close_database()
    with GraphManager() as gm:
        yield gm
    close_database()


def _cfg(params=None):
    return SimpleNamespace(
        node_type="Technology",
        input_sources=json.dumps({"files": [{"type": "dependency", "subtype": "*"}], "nodes": []}),
        instruction="Classify every item.",
        example="",
        params=json.dumps(PARAMS if params is None else params),
        batch_size=50,
        temperature=0.0,
        max_tokens=None,
    )


def _run(tmp_path, graph, llm, cfg=None, files=None):
    files = {"app/package.json": PACKAGE} if files is None else files
    classified = []
    for path, content in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(content, encoding="utf-8")
        graph.add_node(FileNode(name=Path(path).name, path=path, repository_name="r", file_type="dependency", subtype="javascript"), node_id=generate_file_node_id("r", path))
        classified.append({"path": path, "file_type": "dependency", "subtype": "javascript"})
    return service._extract_technologies(cfg or _cfg(), SimpleNamespace(name="r"), tmp_path, classified, graph, llm)


def _configures(graph):
    rows = graph.query("MATCH (t:Graph:Technology)<-[r]-(f:Graph) RETURN f.id AS src, t.id AS dst, type(r) AS rel")
    return sorted((row["src"], row["dst"], row["rel"]) for row in rows)


class TestTechnologyStep:
    def test_platforms_and_named_systems_become_technologies_configured_by_their_files(self, tmp_path, graph):
        result = _run(tmp_path, graph, FakeLlm({"alpha-client": ("system_software", "Store Alpha")}))

        assert (result["nodes_created"], result["edges_created"], result["errors"]) == (2, 2, [])
        store = graph.get_node("tech::r::storealpha")["properties"]
        assert (store["techName"], store["techCategory"], store["confidence"]) == ("Store Alpha", "system_software", 0.9)
        assert graph.get_node("tech::r::runtimejs")["properties"]["techCategory"] == "platform"
        file_id = generate_file_node_id("r", "app/package.json")
        assert _configures(graph) == [(file_id, "tech::r::runtimejs", "Graph:CONFIGURES"), (file_id, "tech::r::storealpha", "Graph:CONFIGURES")]

    def test_the_ids_of_the_created_edges_are_reported_for_the_run_log(self, tmp_path, graph):
        from deriva.common.ocel import create_edge_id

        result = _run(tmp_path, graph, FakeLlm({"alpha-client": ("system_software", "Store Alpha")}))

        file_id = generate_file_node_id("r", "app/package.json")
        assert sorted(result["edge_ids"]) == sorted(create_edge_id(file_id, "CONFIGURES", tech) for tech in ("tech::r::runtimejs", "tech::r::storealpha"))

    def test_the_classifier_gets_the_configured_instruction_and_the_closed_schema(self, tmp_path, graph):
        llm = FakeLlm({})

        _run(tmp_path, graph, llm)

        (call,) = llm.calls
        assert call["prompt"].startswith("Classify every item.\n\nItems:\n")
        assert call["schema"]["name"] == "technology_classification"
        assert call["temperature"] == 0.0

    def test_a_technology_that_exists_before_the_step_keeps_its_node(self, tmp_path, graph):
        graph.add_node(TechnologyNode(name="Store Alpha", tech_category="infrastructure", repository_name="r", confidence=0.9), node_id="tech::r::storealpha")

        result = _run(tmp_path, graph, FakeLlm({"alpha-client": ("system_software", "Store Alpha")}))

        assert result["nodes_created"] == 1  # the platform only
        assert graph.get_node("tech::r::storealpha")["properties"]["techCategory"] == "infrastructure"
        assert (generate_file_node_id("r", "app/package.json"), "tech::r::storealpha", "Graph:CONFIGURES") in _configures(graph)

    def test_items_left_out_of_an_answer_are_asked_again_on_their_own(self, tmp_path, graph):
        llm = FakeLlm({"beta-lib": ("service", "Queue Beta")}, skip={"beta-lib"})

        result = _run(tmp_path, graph, llm)

        assert [llm.prompted_items(i) for i in range(len(llm.calls))] == [["alpha-client", "beta-lib"], ["beta-lib"]]
        assert result["stats"]["decisions"]["npm library::beta-lib"] == {"category": "service", "system": "Queue Beta"}
        assert (result["stats"]["issues"]["missing"], result["stats"]["retries"]) == (0, {"calls": 1, "recovered": 1})

    def test_stats_report_the_items_the_labels_and_the_decisions(self, tmp_path, graph):
        result = _run(tmp_path, graph, FakeLlm({"alpha-client": ("system_software", "Store Alpha")}))

        stats = result["stats"]
        assert (stats["items"], stats["platforms"], stats["batches"]) == ({"npm library": 2}, 1, 1)
        assert stats["labels"] == {"none": 1, "system_software": 1}
        assert stats["decisions"] == {
            "npm library::alpha-client": {"category": "system_software", "system": "Store Alpha"},
            "npm library::beta-lib": {"category": "none", "system": ""},
        }

    def test_missing_params_are_an_error_before_any_work(self, tmp_path, graph):
        llm = FakeLlm({})

        result = _run(tmp_path, graph, llm, cfg=_cfg(params={"confidence": 0.9}))

        assert result["errors"] == ["Technology params missing: missing_retries, platforms"]
        assert llm.calls == []

    def test_a_failed_call_is_an_error_and_leaves_the_platforms(self, tmp_path, graph):
        result = _run(tmp_path, graph, FakeLlm({}, response=SimpleNamespace(content="", error="rate limited")))

        assert result["errors"] == ["LLM error in batch 1: rate limited"]
        assert result["nodes_created"] == 1
        assert result["stats"]["decisions"] == {"npm library::alpha-client": None, "npm library::beta-lib": None}

    def test_compose_services_of_the_repositories_own_modules_are_no_items(self, tmp_path, graph):
        compose = "services:\n  app:\n    image: acme/shop:app\n  store:\n    image: storedb:9\n"
        files = {"app/package.json": (PACKAGE, "dependency", "javascript"), "deploy/docker-compose.yml": (compose, "infra", "docker-compose")}
        classified = []
        for path, (content, file_type, subtype) in files.items():
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_text(content, encoding="utf-8")
            graph.add_node(FileNode(name=Path(path).name, path=path, repository_name="r", file_type=file_type, subtype=subtype), node_id=generate_file_node_id("r", path))
            classified.append({"path": path, "file_type": file_type, "subtype": subtype})
        cfg = _cfg(params={**PARAMS, "own_modules": {"file_types": ["dependency"], "subtypes": ["docker"]}})
        cfg.input_sources = json.dumps({"files": [{"type": "dependency", "subtype": "*"}, {"type": "infra", "subtype": "*"}], "nodes": []})
        llm = FakeLlm({})

        service._extract_technologies(cfg, SimpleNamespace(name="r"), tmp_path, classified, graph, llm)

        # The "app" service runs the repository's own app module (a directory holding a dependency file)
        assert sorted(llm.prompted_items(0)) == ["alpha-client", "beta-lib", "store"]

    @pytest.mark.parametrize("skip, prompted", [(True, ["beta-lib"]), (False, ["alpha-client", "beta-lib"])])
    def test_items_named_after_the_repository_are_skipped_when_configured(self, tmp_path, graph, skip, prompted):
        (tmp_path / "app").mkdir()
        (tmp_path / "app/package.json").write_text(PACKAGE, encoding="utf-8")
        package = FileNode(name="package.json", path="app/package.json", repository_name="alpha", file_type="dependency", subtype="javascript")
        graph.add_node(package, node_id=generate_file_node_id("alpha", "app/package.json"))
        classified = [{"path": "app/package.json", "file_type": "dependency", "subtype": "javascript"}]
        llm = FakeLlm({})

        service._extract_technologies(_cfg(params={**PARAMS, "skip_repository_name": skip}), SimpleNamespace(name="alpha"), tmp_path, classified, graph, llm)

        # The repository "alpha" publishes its own client library; it is no technology the repository uses
        assert sorted(llm.prompted_items(0)) == prompted

    def test_a_non_boolean_skip_repository_name_is_an_error(self, tmp_path, graph):
        llm = FakeLlm({})

        result = _run(tmp_path, graph, llm, cfg=_cfg(params={**PARAMS, "skip_repository_name": "yes"}))

        assert result["errors"] and "skip_repository_name" in result["errors"][0]
        assert llm.calls == []

    @pytest.mark.parametrize("own", [True, {"file_types": "build"}, {"file_types": ["build"], "subtypes": [""]}, {"subtypes": ["docker"]}])
    def test_invalid_own_module_settings_are_an_error(self, tmp_path, graph, own):
        llm = FakeLlm({})

        result = _run(tmp_path, graph, llm, cfg=_cfg(params={**PARAMS, "own_modules": own}))

        assert result["errors"] and "own_modules" in result["errors"][0]
        assert llm.calls == []

    def test_without_input_files_there_is_nothing_to_do(self, tmp_path, graph):
        llm = FakeLlm({})

        result = _run(tmp_path, graph, llm, files={})

        assert (result["nodes_created"], result["errors"], llm.calls) == (0, [], [])
        assert result["warnings"] == ["No input files for Technology in r"]


def test_the_step_runs_the_structure_flow(tmp_path):
    cfg = SimpleNamespace(node_type="Technology", extraction_method="llm")

    with patch.object(service, "_extract_technologies", return_value={"nodes_created": 2, "edges_created": 0, "errors": []}) as step:
        result = service._run_extraction_step(cfg, SimpleNamespace(name="r"), tmp_path, [], [], None, lambda *a, **k: None, None)

    assert result["nodes_created"] == 2
    step.assert_called_once()
