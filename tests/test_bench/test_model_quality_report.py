"""Model quality per benchmark run, read from the models the benchmark exports."""

from __future__ import annotations

from pathlib import Path

from deriva.adapters.archimate.models import Element, Relationship
from deriva.adapters.archimate.xml_export import ArchiMateXMLExporter
from deriva.bench.benchmarking import model_quality_for_session


def _export(path: Path, elements: list[Element], relationships: list[Relationship]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ArchiMateXMLExporter().export(elements=elements, relationships=relationships, output_path=str(path), model_name="test")


SHOP = Element(name="Shop", element_type="ApplicationComponent", identifier="ac_shop")
ORDERING = Element(name="Ordering", element_type="ApplicationService", identifier="as_ordering")
HOST = Element(name="Host", element_type="Node", identifier="node_host")


class TestModelQualityForSession:
    def test_one_entry_per_exported_run_with_the_structural_measures(self, tmp_path):
        realizes = Relationship(source="ac_shop", target="as_ordering", relationship_type="Realization", identifier="r1")
        _export(tmp_path / "models" / "shop-repo_model-a_run1.xml", [SHOP, ORDERING, HOST], [realizes])
        _export(tmp_path / "models" / "shop-repo_model-a_run2.xml", [SHOP, ORDERING], [])

        rows = model_quality_for_session(tmp_path, ["shop-repo"], ["model-a"], reference_models={})

        assert [(r["repository"], r["model"], r["run"]) for r in rows] == [("shop-repo", "model-a", 1), ("shop-repo", "model-a", 2)]
        assert (rows[0]["elements"], rows[0]["relationships"], rows[0]["orphans"]) == (3, 1, 1)
        assert rows[0]["chains"]["ApplicationService-ApplicationComponent"] == (1, 1)
        assert rows[1]["orphans"] == 2
        assert rows[0]["reference"] is None

    def test_only_the_architect_level_is_measured(self, tmp_path):
        """The export holds both levels; the benchmark measures the architect level (detail elements are reported apart)."""
        path = tmp_path / "models" / "shop-repo_model-a_run1.xml"
        path.parent.mkdir(parents=True)
        line = Element(name="Order Line", element_type="DataObject", identifier="do_line")
        composes = Relationship(source="ac_shop", target="do_line", relationship_type="Access", identifier="r2")
        levels = {"ac_shop": {"level": "architect"}, "as_ordering": {"level": "architect"}, "do_line": {"level": "detail"}}
        ArchiMateXMLExporter().export([SHOP, ORDERING, line], [composes], str(path), model_name="test", properties=levels)

        rows = model_quality_for_session(tmp_path, ["shop-repo"], ["model-a"], reference_models={})

        assert (rows[0]["elements"], rows[0]["relationships"]) == (2, 0)

    def test_names_are_matched_against_the_reference_model(self, tmp_path):
        _export(tmp_path / "models" / "shop-repo_model-a_run1.xml", [SHOP, ORDERING], [])
        reference = tmp_path / "reference.xml"
        _export(
            reference,
            [
                Element(name="Shop", element_type="ApplicationComponent", identifier="ref_shop"),
                Element(name="Billing", element_type="ApplicationService", identifier="ref_billing"),
            ],
            [],
        )

        rows = model_quality_for_session(tmp_path, ["shop-repo"], ["model-a"], reference_models={"shop-repo": str(reference)})

        # Shop matches, Ordering does not: half of the derived and half of the reference elements
        assert rows[0]["reference"]["precision"] == 0.5
        assert rows[0]["reference"]["recall"] == 0.5

    def test_each_run_carries_the_solve_report_of_its_snapshot(self, tmp_path):
        import json

        _export(tmp_path / "models" / "shop-repo_model-a_run1.xml", [SHOP], [])
        _export(tmp_path / "models" / "shop-repo_model-a_run2.xml", [SHOP], [])
        solve = {"status": "optimal", "rows": {"H1": 2}, "dropped": 2}
        (tmp_path / "models" / "shop-repo_model-a_run1.json").write_text(json.dumps({"elements": [], "relationships": [], "solve": solve}), encoding="utf-8")

        rows = model_quality_for_session(tmp_path, ["shop-repo"], ["model-a"], reference_models={})

        assert rows[0]["solve"] == solve
        assert rows[1]["solve"] is None  # no snapshot (or an older one without the report)

    def test_a_session_without_exported_models_has_no_rows(self, tmp_path):
        assert model_quality_for_session(tmp_path, ["shop-repo"], ["model-a"], reference_models={}) == []


class TestAnalysisSummary:
    def test_the_full_analysis_reports_model_quality_per_run(self):
        from unittest.mock import MagicMock, patch

        from deriva.bench.benchmarking import BenchmarkAnalyzer
        from deriva.common.ocel import OCELLog

        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = ("sess-1", "Test", '{"repositories": ["shop-repo"], "models": ["model-a"]}', "completed", "2026-01-01", "2026-01-01")
        rows = [{"repository": "shop-repo", "model": "model-a", "run": 1, "elements": 3}]
        with (
            patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=OCELLog()),
            patch("deriva.bench.benchmarking.get_benchmark_runs", return_value=[]),
            patch("deriva.bench.benchmarking.model_quality_for_session", return_value=rows) as quality,
        ):
            summary = BenchmarkAnalyzer("sess-1", engine).compute_full_analysis()

        assert summary.model_quality == rows
        assert summary.to_dict()["model_quality"] == rows
        assert quality.call_args.args[1:] == (["shop-repo"], ["model-a"])

    def test_the_markdown_report_has_a_model_quality_table(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from deriva.bench.benchmarking import BenchmarkAnalyzer
        from deriva.common.ocel import OCELLog

        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = ("sess-1", "Test", "{}", "completed", "2026-01-01", "2026-01-01")
        row = {
            "repository": "shop-repo",
            "model": "model-a",
            "run": 1,
            "elements": 3,
            "relationships": 1,
            "relationships_per_element": 0.33,
            "orphan_share": 0.333,
            "composition_violations": 0,
            "duplicate_pairs": 0,
            "duplicate_elements": 2,
            "reference": {"precision": 0.5, "recall": 0.25},
        }
        with (
            patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=OCELLog()),
            patch("deriva.bench.benchmarking.get_benchmark_runs", return_value=[]),
            patch("deriva.bench.benchmarking.model_quality_for_session", return_value=[row]),
        ):
            path = BenchmarkAnalyzer("sess-1", engine).export_summary(str(tmp_path / "summary.md"), format="markdown")

        text = (tmp_path / "summary.md").read_text(encoding="utf-8")
        assert path.endswith("summary.md")
        assert "## Model Quality" in text
        assert "| Orphan % |" in text and "| Duplicate elements |" in text
        assert "| shop-repo | model-a | 1 | 3 | 1 | 0.33 | 33% | 0 | 0 | 2 | 0.50 / 0.25 |" in text


class TestReferenceMatching:
    def test_a_name_match_of_another_type_does_not_count(self, tmp_path):
        _export(tmp_path / "models" / "shop-repo_model-a_run1.xml", [Element(name="Order Service", element_type="ApplicationComponent", identifier="ac_order")], [])
        reference = tmp_path / "reference.xml"
        _export(reference, [Element(name="Order Service", element_type="ApplicationService", identifier="ref_order")], [])

        rows = model_quality_for_session(tmp_path, ["shop-repo"], ["model-a"], reference_models={"shop-repo": str(reference)})

        assert rows[0]["reference"]["precision"] == 0.0

    def test_duplicates_match_a_reference_element_once(self, tmp_path):
        twin = Element(name="Shop", element_type="ApplicationComponent", identifier="ac_shop_twin")
        _export(tmp_path / "models" / "shop-repo_model-a_run1.xml", [SHOP, twin], [])
        reference = tmp_path / "reference.xml"
        _export(
            reference,
            [
                Element(name="Shop", element_type="ApplicationComponent", identifier="ref_shop"),
                Element(name="Billing", element_type="ApplicationService", identifier="ref_billing"),
            ],
            [],
        )

        rows = model_quality_for_session(tmp_path, ["shop-repo"], ["model-a"], reference_models={"shop-repo": str(reference)})

        # One of the two Shops matches; the second one costs precision
        assert rows[0]["reference"]["precision"] == 0.5
        assert rows[0]["reference"]["recall"] == 0.5


class TestCombinedSessions:
    def test_a_combined_session_reads_the_model_of_the_joined_repositories(self, tmp_path):
        _export(tmp_path / "models" / "alpha_beta_model-a_run1.xml", [SHOP], [])

        rows = model_quality_for_session(tmp_path, ["beta", "alpha"], ["model-a"], reference_models={"alpha": "unused.xml"})

        assert [(r["repository"], r["run"], r["reference"]) for r in rows] == [("alpha_beta", 1, None)]


class TestDetailLevelForSession:
    """The export's detail level, reported apart from the architect level: its size and its consistency over runs."""

    @staticmethod
    def _snapshot(path: Path, detail: list[tuple[str, str]], relationships: list[tuple[str, str]]) -> None:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "elements": [],
            "detail": {
                "elements": [{"identifier": i, "type": t, "name": i, "level": "detail"} for i, t in detail],
                "relationships": [{"source": s, "target": t, "type": "Composition"} for s, t in relationships],
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_detail_elements_and_their_consistency_per_repository(self, tmp_path):
        from deriva.bench.benchmarking import detail_level_for_session

        models = tmp_path / "models"
        self._snapshot(models / "shop-repo_model-a_run1.json", [("do_a", "DataObject"), ("ai_x", "ApplicationInterface")], [("p", "do_a")])
        self._snapshot(models / "shop-repo_model-a_run2.json", [("do_a", "DataObject"), ("ai_y", "ApplicationInterface")], [("p", "do_a")])
        self._snapshot(models / "other_model-a_run1.json", [], [])  # an older snapshot or an empty detail level

        rows = detail_level_for_session(tmp_path, ["shop-repo"], ["model-a"])

        assert rows == [
            {
                "repository": "shop-repo",
                "model": "model-a",
                "runs": 2,
                "elements": 2.0,
                "by_type": {"ApplicationInterface": 1.0, "DataObject": 1.0},
                "element_consistency": round(1 / 3, 3),  # do_a in every run, of do_a, ai_x, ai_y
                "relationship_consistency": 1.0,
            }
        ]
