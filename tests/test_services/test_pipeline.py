"""Tests for services.pipeline module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from deriva.services.pipeline import (
    get_pipeline_status,
    run_classification,
    run_full_pipeline,
)


class TestRunFullPipeline:
    """Tests for run_full_pipeline function."""

    def test_runs_all_stages(self):
        """Should run all stages when none are skipped."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        llm_query_fn = MagicMock()

        with patch("deriva.services.pipeline.run_classification") as mock_class:
            mock_class.return_value = {"success": True, "stats": {}}

            with patch("deriva.services.pipeline.extraction.run_extraction") as mock_extract:
                mock_extract.return_value = {"success": True, "stats": {}}

                with patch("deriva.services.pipeline.derivation.run_derivation") as mock_derive:
                    mock_derive.return_value = {"success": True, "stats": {}}

                    result = run_full_pipeline(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=llm_query_fn,
                    )

        assert result["success"] is True
        assert result["results"]["classification"] is not None
        assert result["results"]["extraction"] is not None
        assert result["results"]["derivation"] is not None

    def test_skips_classification(self):
        """Should skip classification when requested."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        llm_query_fn = MagicMock()

        with patch("deriva.services.pipeline.run_classification") as mock_class:
            with patch("deriva.services.pipeline.extraction.run_extraction") as mock_extract:
                mock_extract.return_value = {"success": True, "stats": {}}

                with patch("deriva.services.pipeline.derivation.run_derivation") as mock_derive:
                    mock_derive.return_value = {"success": True, "stats": {}}

                    result = run_full_pipeline(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=llm_query_fn,
                        skip_classification=True,
                    )

        mock_class.assert_not_called()
        assert result["results"]["classification"] is None

    def test_skips_extraction(self):
        """Should skip extraction when requested."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        llm_query_fn = MagicMock()

        with patch("deriva.services.pipeline.run_classification") as mock_class:
            mock_class.return_value = {"success": True, "stats": {}}

            with patch("deriva.services.pipeline.extraction.run_extraction") as mock_extract:
                with patch("deriva.services.pipeline.derivation.run_derivation") as mock_derive:
                    mock_derive.return_value = {"success": True, "stats": {}}

                    result = run_full_pipeline(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=llm_query_fn,
                        skip_extraction=True,
                    )

        mock_extract.assert_not_called()
        assert result["results"]["extraction"] is None

    def test_skips_derivation(self):
        """Should skip derivation when requested."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        llm_query_fn = MagicMock()

        with patch("deriva.services.pipeline.run_classification") as mock_class:
            mock_class.return_value = {"success": True, "stats": {}}

            with patch("deriva.services.pipeline.extraction.run_extraction") as mock_extract:
                mock_extract.return_value = {"success": True, "stats": {}}

                with patch("deriva.services.pipeline.derivation.run_derivation") as mock_derive:
                    result = run_full_pipeline(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=llm_query_fn,
                        skip_derivation=True,
                    )

        mock_derive.assert_not_called()
        assert result["results"]["derivation"] is None

    def test_accumulates_errors(self):
        """Should accumulate errors from failed stages."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        llm_query_fn = MagicMock()

        with patch("deriva.services.pipeline.run_classification") as mock_class:
            mock_class.return_value = {"success": False, "errors": ["Classification error"]}

            with patch("deriva.services.pipeline.extraction.run_extraction") as mock_extract:
                mock_extract.return_value = {"success": False, "errors": ["Extraction error"]}

                with patch("deriva.services.pipeline.derivation.run_derivation") as mock_derive:
                    mock_derive.return_value = {"success": True}

                    result = run_full_pipeline(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=llm_query_fn,
                    )

        assert result["success"] is False
        assert "Classification error" in result["errors"]
        assert "Extraction error" in result["errors"]


class TestRunClassification:
    """Tests for run_classification function."""

    def test_returns_error_when_no_repos(self):
        """Should return error when no repositories found."""
        engine = MagicMock()

        with patch("deriva.services.pipeline.RepoManager") as mock_repo_mgr:
            mock_repo_mgr.return_value.list_repositories.return_value = []

            result = run_classification(engine)

        assert result["success"] is False
        assert "No repositories found" in result["errors"]

    def test_classifies_files_in_repo(self):
        """Should classify files in repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some files
            (Path(tmpdir) / "main.py").write_text("def main(): pass")
            (Path(tmpdir) / "README.md").write_text("# Test")

            engine = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir

            with patch("deriva.services.pipeline.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.pipeline.config.get_file_types") as mock_ft:
                    mock_file_type = MagicMock()
                    mock_file_type.extension = ".py"
                    mock_file_type.file_type = "source"
                    mock_file_type.subtype = "python"
                    mock_ft.return_value = [mock_file_type]

                    result = run_classification(engine)

        assert result["success"] is True
        assert result["stats"]["repos_processed"] == 1
        assert result["stats"]["files_classified"] >= 0

    def test_filters_by_repo_name(self):
        """Should filter to specific repo when name provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()

            mock_repo1 = MagicMock()
            mock_repo1.name = "repo1"
            mock_repo1.path = tmpdir  # Use real temp path

            mock_repo2 = MagicMock()
            mock_repo2.name = "repo2"
            mock_repo2.path = "/path/to/repo2"

            with patch("deriva.services.pipeline.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo1, mock_repo2]

                with patch("deriva.services.pipeline.config.get_file_types") as mock_ft:
                    mock_ft.return_value = []

                    result = run_classification(engine, repo_name="repo1")

            # Should only process repo1
            assert result["stats"]["repos_processed"] == 1


class TestGetPipelineStatus:
    """Tests for get_pipeline_status function."""

    def test_returns_extraction_status(self):
        """Should return extraction configuration status."""
        engine = MagicMock()

        mock_extract_cfg1 = MagicMock()
        mock_extract_cfg1.node_type = "BusinessConcept"
        mock_extract_cfg1.enabled = True

        mock_extract_cfg2 = MagicMock()
        mock_extract_cfg2.node_type = "TypeDefinition"
        mock_extract_cfg2.enabled = False

        with patch("deriva.services.pipeline.config.get_extraction_configs") as mock_get_extract:
            mock_get_extract.return_value = [mock_extract_cfg1, mock_extract_cfg2]

            with patch("deriva.services.pipeline.config.get_derivation_configs") as mock_get_derive:
                mock_get_derive.return_value = []

                status = get_pipeline_status(engine)

        assert status["extraction"]["total"] == 2
        assert status["extraction"]["enabled"] == 1
        assert "BusinessConcept" in status["extraction"]["steps"]

    def test_returns_derivation_status(self):
        """Should return derivation configuration status."""
        engine = MagicMock()

        mock_derive_cfg1 = MagicMock()
        mock_derive_cfg1.step_name = "PageRank"
        mock_derive_cfg1.phase = "enrich"
        mock_derive_cfg1.enabled = True

        mock_derive_cfg2 = MagicMock()
        mock_derive_cfg2.step_name = "ApplicationComponent"
        mock_derive_cfg2.phase = "generate"
        mock_derive_cfg2.enabled = True

        with patch("deriva.services.pipeline.config.get_extraction_configs") as mock_get_extract:
            mock_get_extract.return_value = []

            with patch("deriva.services.pipeline.config.get_derivation_configs") as mock_get_derive:
                mock_get_derive.return_value = [mock_derive_cfg1, mock_derive_cfg2]

                status = get_pipeline_status(engine)

        assert status["derivation"]["total"] == 2
        assert status["derivation"]["enabled"] == 2
        assert status["derivation"]["by_phase"]["enrich"] == 1
        assert status["derivation"]["by_phase"]["generate"] == 1

    def test_returns_empty_when_no_configs(self):
        """Should return empty lists when no configs exist."""
        engine = MagicMock()

        with patch("deriva.services.pipeline.config.get_extraction_configs") as mock_get_extract:
            mock_get_extract.return_value = []

            with patch("deriva.services.pipeline.config.get_derivation_configs") as mock_get_derive:
                mock_get_derive.return_value = []

                status = get_pipeline_status(engine)

        assert status["extraction"]["total"] == 0
        assert status["extraction"]["enabled"] == 0
        assert status["derivation"]["total"] == 0
