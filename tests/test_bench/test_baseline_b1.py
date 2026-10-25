"""Baseline B1: one template-driven generation of a whole ArchiMate model from raw repository material, validated and
repaired at most N times (k = 1, no sampling)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from deriva.bench import baseline_b1 as b1

PARAMS = b1.B1Params(budget_chars=2000, readme_chars=100, tree_depth=2, tree_entries=50, per_file_chars=300, max_repairs=2)


def _repo(tmp_path):
    root = tmp_path / "r"
    files = {
        "README.md": "# Shop\n" + "about the shop " * 20,
        "package.json": '{"name": "shop"}',
        "src/orders/OrderService.java": "class OrderService {}\n" * 40,
        "src/orders/Order.java": "class Order {}\n" * 5,
        "src/orders/OrderServiceTest.java": "class OrderServiceTest {}\n" * 80,  # a test: never sampled
        "docker-compose.yml": "services:\n  shop:\n    build: .\n",
    }
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    return root


def test_the_material_is_deterministic_and_within_budget(tmp_path):
    root = _repo(tmp_path)

    text, manifest = b1.repository_material(root, PARAMS)
    again, _ = b1.repository_material(root, PARAMS)

    assert text == again and len(text) <= PARAMS.budget_chars
    assert manifest["readme"] == "README.md" and manifest["manifests"] == ["docker-compose.yml", "package.json"]
    # Sources by size (largest first), no tests
    assert manifest["sources"][0] == "src/orders/OrderService.java" and "src/orders/OrderServiceTest.java" not in manifest["sources"]
    assert "src/" in text and "## Directory tree" in text


def test_files_the_registry_excludes_are_no_material_not_even_in_the_tree(tmp_path):
    root = _repo(tmp_path)
    for path in ("design/model.archimate", "design/notes/Model.docx", "src/orders/Legacy.java"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("reference " * 10, encoding="utf-8")
    registry = [
        {"extension": ".archimate", "file_type": "exclude", "subtype": "output"},
        {"extension": "path:**/notes/Model.docx", "file_type": "exclude", "subtype": "reference-model"},
        {"extension": "path:**/Legacy.java", "file_type": "exclude", "subtype": ""},
        {"extension": ".java", "file_type": "source", "subtype": "java"},
    ]
    params = b1.B1Params(budget_chars=5000, readme_chars=100, tree_depth=4, tree_entries=50, per_file_chars=300)

    text, manifest = b1.repository_material(root, params, registry)

    assert "model.archimate" not in text and "Model.docx" not in text and "Legacy.java" not in text
    assert "design/" not in text  # a folder holding only excluded files is not listed either
    assert manifest["sources"][0] == "src/orders/OrderService.java" and manifest["excluded"] == 3


def test_validation_names_every_problem():
    model = {
        "elements": [
            {"id": "a", "type": "ApplicationComponent", "name": "Shop"},
            {"id": "a", "type": "ApplicationService", "name": "Ordering"},
            {"id": "b", "type": "DataObject", "name": "Order"},
        ],
        "relationships": [
            {"source": "a", "target": "zz", "type": "Serving"},
            {"source": "b", "target": "a", "type": "Assignment"},  # a data object assigns nothing
        ],
    }

    errors = b1.validate(model)

    assert any("duplicate id a" in e for e in errors)
    assert any("unknown target zz" in e for e in errors)
    assert any("Assignment from DataObject" in e for e in errors)


def test_errors_are_repaired_at_most_n_times_then_invalid_relationships_are_dropped():
    bad = {"elements": [{"id": "a", "type": "ApplicationComponent", "name": "Shop"}], "relationships": [{"source": "a", "target": "x", "type": "Serving"}]}
    calls = []

    def llm(prompt, schema, **kwargs):
        calls.append(prompt)
        return SimpleNamespace(content=json.dumps(bad))

    model, report = b1.generate(llm, "MAKE A MODEL", "material", PARAMS)

    assert len(calls) == 1 + PARAMS.max_repairs
    assert "## Errors" in calls[1] and "unknown target x" in calls[1]
    assert model["relationships"] == [] and len(model["elements"]) == 1
    assert report == {"calls": 3, "repairs": 2, "errors_left": 1, "dropped_relationships": 1, "dropped_elements": 0, "parse_failures": 0}


def test_a_valid_first_answer_needs_one_call():
    good = {
        "elements": [{"id": "a", "type": "ApplicationComponent", "name": "Shop"}, {"id": "s", "type": "ApplicationService", "name": "Ordering"}],
        "relationships": [{"source": "a", "target": "s", "type": "Realization"}],
    }

    model, report = b1.generate(lambda p, s, **k: SimpleNamespace(content=json.dumps(good)), "MAKE", "m", PARAMS)

    assert report["calls"] == 1 and report["errors_left"] == 0 and len(model["relationships"]) == 1


def test_the_model_gets_identities_from_type_and_name():
    model = {
        "elements": [{"id": "e1", "type": "ApplicationComponent", "name": "Order Service"}, {"id": "e2", "type": "DataObject", "name": "Order"}],
        "relationships": [{"source": "e1", "target": "e2", "type": "Access"}],
    }

    elements, relationships = b1.to_archimate(model)

    assert [e.identifier for e in elements] == [b1.element_id("ApplicationComponent", "Order Service"), b1.element_id("DataObject", "Order")]
    assert relationships[0].source == elements[0].identifier and relationships[0].properties["derived_from"] == "llm_b1"


def test_a_b1_run_generates_instead_of_extracting_and_deriving(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch

    from deriva.bench.benchmarking import BenchmarkConfig, BenchmarkOrchestrator

    monkeypatch.setenv("DERIVA_HOME", str(tmp_path))
    root = _repo(tmp_path)
    archimate = MagicMock()
    orchestrator = BenchmarkOrchestrator(
        engine=MagicMock(),
        graph_manager=MagicMock(),
        archimate_manager=archimate,
        config=BenchmarkConfig(repositories=["r"], models=["m"], use_cache=False, baseline="b1", export_models=False, runs_per_combination=1),
    )
    orchestrator.session_id = "s"
    orchestrator._model_configs = {"m": MagicMock(model="x")}
    model = {"elements": [{"id": "a", "type": "ApplicationComponent", "name": "Shop"}], "relationships": []}
    row = SimpleNamespace(instruction="MAKE A MODEL", params=json.dumps({"budget_chars": 2000}))
    with (
        patch("deriva.bench.benchmarking.config_service.get_derivation_config", return_value=row),
        patch("deriva.bench.benchmarking.config_service.get_excluded_directories", return_value=[".git"]),
        patch("deriva.bench.benchmarking.RepoManager") as repos,
        patch("deriva.bench.benchmarking.baseline_b1.generate", return_value=(model, {"calls": 1})) as generate,
        patch("deriva.bench.benchmarking.derivation.run_derivation") as derive,
        patch("deriva.bench.benchmarking.LLMManager.from_config"),
        patch("deriva.bench.benchmarking.use_database"),
        patch("deriva.bench.benchmarking.close_database"),
        patch("deriva.bench.benchmarking.database_file", return_value=None),
        patch.object(orchestrator, "_extract_repo") as extract,
        patch.object(orchestrator, "_create_run"),
        patch.object(orchestrator, "_complete_run"),
    ):
        repos.return_value.list_repositories.return_value = [SimpleNamespace(name="r", path=str(root))]
        result = orchestrator._run_combined(repositories=["r"], model_name="m", iteration=1)

    assert result.status == "completed"
    extract.assert_not_called()
    derive.assert_not_called()
    assert generate.call_args.args[1] == "MAKE A MODEL" and "## README" in generate.call_args.args[2]
    (added,) = [c.args[0] for c in archimate.add_element.call_args_list]
    assert added.identifier == b1.element_id("ApplicationComponent", "Shop")
    assert result.stats["baseline"]["r"]["elements"] == 1 and result.stats["baseline"]["r"]["material"]["readme"] == "README.md"


def test_the_baseline_needs_no_cache_and_no_extraction_per_run():
    import pytest

    from deriva.bench.benchmarking import BenchmarkConfig, validate_config

    with pytest.raises(ValueError, match="--no-cache"):
        validate_config(BenchmarkConfig(repositories=["r"], models=["m"], baseline="b1"))
    with pytest.raises(ValueError, match="extract-per-run"):
        validate_config(BenchmarkConfig(repositories=["r"], models=["m"], baseline="b1", use_cache=False, extract_per_run=True))
    with pytest.raises(ValueError, match="Unknown baseline"):
        validate_config(BenchmarkConfig(repositories=["r"], models=["m"], baseline="b2", use_cache=False))
