"""Tests for services.extraction module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from deriva.services.extraction import (
    _build_llm_prompt,
    _create_node_from_data,
    _extract_directories,
    _extract_file_content,
    _extract_files,
    _extract_llm_based,
    _extract_repository,
    _get_extraction_config,
    _run_extraction_step,
    run_extraction,
)


class TestRunExtraction:
    """Tests for run_extraction function."""

    def test_returns_error_when_no_repos(self):
        """Should return error when no repositories found."""
        engine = MagicMock()
        graph_manager = MagicMock()

        with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
            mock_repo_mgr.return_value.list_repositories.return_value = []

            result = run_extraction(engine, graph_manager)

        assert result["success"] is False
        assert "No repositories found" in result["errors"]

    def test_returns_error_when_no_configs(self):
        """Should return error when no extraction configs enabled."""
        engine = MagicMock()
        graph_manager = MagicMock()

        mock_repo = MagicMock()
        mock_repo.name = "test_repo"
        mock_repo.path = "/path/to/repo"

        with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
            mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

            with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                mock_cfg.return_value = []

                result = run_extraction(engine, graph_manager)

        assert result["success"] is False
        assert "No extraction configs enabled" in result["errors"]

    def test_filters_repos_by_name(self):
        """Should filter repositories by name when specified."""
        engine = MagicMock()
        graph_manager = MagicMock()

        mock_repo1 = MagicMock()
        mock_repo1.name = "repo1"
        mock_repo1.path = "/path/to/repo1"

        mock_repo2 = MagicMock()
        mock_repo2.name = "repo2"
        mock_repo2.path = "/path/to/repo2"

        with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
            mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo1, mock_repo2]

            with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                mock_cfg.return_value = []

                result = run_extraction(engine, graph_manager, repo_name="repo1")

        # Should try to process only repo1, but fail due to no configs
        assert result["success"] is False

    def test_processes_repository_extraction(self):
        """Should process repository extraction step."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple file structure
            (Path(tmpdir) / "src").mkdir()
            (Path(tmpdir) / "src" / "main.py").write_text("def main(): pass")

            engine = MagicMock()
            graph_manager = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "Repository"
            mock_config.input_sources = None

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        result = run_extraction(engine, graph_manager)

            assert result["success"] is True
            assert result["stats"]["repos_processed"] == 1
            assert result["stats"]["steps_completed"] >= 1

    def test_handles_extraction_error(self):
        """Should handle extraction step errors gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "UnknownType"
            mock_config.input_sources = None

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        result = run_extraction(engine, graph_manager)

            # Unknown type causes an error
            assert any("Unknown node type" in str(e) for e in result["errors"])


class TestExtractRepository:
    """Tests for _extract_repository function."""

    def test_extracts_repository_node(self):
        """Should extract repository node from metadata."""
        mock_repo = MagicMock()
        mock_repo.name = "myproject"
        mock_repo.url = "https://github.com/user/myproject.git"
        mock_repo.branch = "main"

        graph_manager = MagicMock()

        result = _extract_repository(mock_repo, graph_manager)

        assert result["nodes_created"] >= 1
        graph_manager.add_node.assert_called()


class TestExtractDirectories:
    """Tests for _extract_directories function."""

    def test_extracts_directory_nodes(self):
        """Should extract directory nodes from repo path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create directory structure
            (Path(tmpdir) / "src").mkdir()
            (Path(tmpdir) / "src" / "utils").mkdir()
            (Path(tmpdir) / "tests").mkdir()

            mock_repo = MagicMock()
            mock_repo.name = "myproject"

            graph_manager = MagicMock()

            result = _extract_directories(mock_repo, Path(tmpdir), graph_manager)

            assert result["nodes_created"] >= 1
            graph_manager.add_node.assert_called()


class TestExtractFiles:
    """Tests for _extract_files function."""

    def test_extracts_file_nodes(self):
        """Should extract file nodes with classification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files
            (Path(tmpdir) / "main.py").write_text("def main(): pass")
            (Path(tmpdir) / "README.md").write_text("# Project")

            mock_repo = MagicMock()
            mock_repo.name = "myproject"

            classified_files = [
                {"path": "main.py", "file_type": "source", "subtype": "python"},
                {"path": "README.md", "file_type": "documentation", "subtype": "markdown"},
            ]

            graph_manager = MagicMock()

            result = _extract_files(mock_repo, Path(tmpdir), classified_files, [], graph_manager)

            assert result["nodes_created"] >= 1
            graph_manager.add_node.assert_called()


class TestExtractLLMBased:
    """Tests for _extract_llm_based function."""

    def test_returns_error_without_input_sources(self):
        """Should return error when no input sources configured."""
        mock_cfg = MagicMock()
        mock_cfg.node_type = "BusinessConcept"
        mock_cfg.input_sources = None

        mock_repo = MagicMock()
        mock_repo.name = "myproject"

        result = _extract_llm_based(
            node_type="BusinessConcept",
            cfg=mock_cfg,
            repo=mock_repo,
            repo_path=Path("/tmp"),
            classified_files=[],
            graph_manager=MagicMock(),
            llm_query_fn=MagicMock(),
            engine=MagicMock(),
        )

        assert result["nodes_created"] == 0
        assert any("No input sources" in str(e) for e in result["errors"])

    def test_returns_empty_when_no_matching_files(self):
        """Should return empty result when no files match input sources."""
        import json as json_module

        mock_cfg = MagicMock()
        mock_cfg.node_type = "BusinessConcept"
        # Use proper JSON format for input_sources
        mock_cfg.input_sources = json_module.dumps({"files": [{"type": "source", "subtype": "python"}]})
        mock_cfg.instruction = None
        mock_cfg.example = None

        mock_repo = MagicMock()
        mock_repo.name = "myproject"

        # No matching files (markdown, not python)
        classified_files = [
            {"path": "README.md", "file_type": "documentation", "subtype": "markdown"},
        ]

        result = _extract_llm_based(
            node_type="BusinessConcept",
            cfg=mock_cfg,
            repo=mock_repo,
            repo_path=Path("/tmp"),
            classified_files=classified_files,
            graph_manager=MagicMock(),
            llm_query_fn=MagicMock(),
            engine=MagicMock(),
        )

        assert result["nodes_created"] == 0
        assert result["errors"] == []

    def test_processes_matching_files(self):
        """Should process files matching input sources."""
        import json as json_module

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Python file
            (Path(tmpdir) / "main.py").write_text("class MyService: pass")

            mock_cfg = MagicMock()
            mock_cfg.node_type = "BusinessConcept"
            # Use proper JSON format for input_sources
            mock_cfg.input_sources = json_module.dumps({"files": [{"type": "source", "subtype": "python"}]})
            mock_cfg.instruction = "Extract business concepts"
            mock_cfg.example = None
            mock_cfg.batch_size = 1

            mock_repo = MagicMock()
            mock_repo.name = "myproject"

            classified_files = [
                {"path": "main.py", "file_type": "source", "subtype": "python"},
            ]

            graph_manager = MagicMock()

            # Mock LLM to return a valid response
            def mock_llm(prompt, schema):
                return {
                    "concepts": [
                        {
                            "name": "MyService",
                            "type": "service",
                            "description": "A service class",
                        }
                    ]
                }

            with patch("deriva.services.extraction._extract_file_content") as mock_extract:
                mock_extract.return_value = (
                    [{"properties": {"name": "MyService", "concept_type": "service", "description": "A service"}}],
                    [],
                    [],
                )

                result = _extract_llm_based(
                    node_type="BusinessConcept",
                    cfg=mock_cfg,
                    repo=mock_repo,
                    repo_path=Path(tmpdir),
                    classified_files=classified_files,
                    graph_manager=graph_manager,
                    llm_query_fn=mock_llm,
                    engine=MagicMock(),
                )

            assert result["nodes_created"] >= 1


class TestExtractFileContent:
    """Tests for _extract_file_content function."""

    def test_extracts_small_file_without_chunking(self):
        """Should extract from small file without chunking."""
        content = "def hello(): pass"

        def mock_extract_fn(file_path, content, repo_name, llm_fn, config):
            return {
                "success": True,
                "data": {
                    "nodes": [{"properties": {"name": "hello"}}],
                    "edges": [],
                },
            }

        nodes, edges, errors = _extract_file_content(
            file_path="main.py",
            content=content,
            repo_name="myrepo",
            extract_fn=mock_extract_fn,
            extraction_config={},
            llm_query_fn=MagicMock(),
        )

        assert len(nodes) == 1
        assert nodes[0]["properties"]["name"] == "hello"
        assert errors == []

    def test_handles_extraction_failure(self):
        """Should handle extraction failure gracefully."""
        content = "def hello(): pass"

        def mock_extract_fn(file_path, content, repo_name, llm_fn, config):
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": ["LLM error"],
            }

        nodes, edges, errors = _extract_file_content(
            file_path="main.py",
            content=content,
            repo_name="myrepo",
            extract_fn=mock_extract_fn,
            extraction_config={},
            llm_query_fn=MagicMock(),
        )

        assert len(nodes) == 0
        assert "LLM error" in errors


class TestGetExtractionConfig:
    """Tests for _get_extraction_config function."""

    def test_returns_config_for_business_concept(self):
        """Should return extraction config for BusinessConcept."""
        extract_fn, schema, node_class = _get_extraction_config("BusinessConcept")

        assert extract_fn is not None
        assert schema is not None
        assert node_class is not None

    def test_returns_config_for_type_definition(self):
        """Should return extraction config for TypeDefinition."""
        extract_fn, schema, node_class = _get_extraction_config("TypeDefinition")

        assert extract_fn is not None
        assert schema is not None

    def test_returns_config_for_method(self):
        """Should return extraction config for Method."""
        extract_fn, schema, node_class = _get_extraction_config("Method")

        assert extract_fn is not None
        assert schema is not None

    def test_returns_config_for_technology(self):
        """Should return extraction config for Technology."""
        extract_fn, schema, node_class = _get_extraction_config("Technology")

        assert extract_fn is not None
        assert schema is not None

    def test_returns_config_for_external_dependency(self):
        """Should return extraction config for ExternalDependency."""
        extract_fn, schema, node_class = _get_extraction_config("ExternalDependency")

        assert extract_fn is not None
        assert schema is not None

    def test_returns_config_for_test(self):
        """Should return extraction config for Test."""
        extract_fn, schema, node_class = _get_extraction_config("Test")

        assert extract_fn is not None
        assert schema is not None

    def test_returns_none_for_unknown_type(self):
        """Should return None for unknown node type."""
        extract_fn, schema, node_class = _get_extraction_config("UnknownType")

        assert extract_fn is None
        assert schema is None
        assert node_class is None


class TestBuildLLMPrompt:
    """Tests for _build_llm_prompt function."""

    def test_builds_basic_prompt(self):
        """Should build basic prompt with content."""
        prompt = _build_llm_prompt(
            node_type="BusinessConcept",
            content="class MyService: pass",
            instruction=None,
            example=None,
        )

        assert "BusinessConcept" in prompt
        assert "class MyService: pass" in prompt

    def test_includes_instruction(self):
        """Should include instruction in prompt."""
        prompt = _build_llm_prompt(
            node_type="BusinessConcept",
            content="class MyService: pass",
            instruction="Focus on service patterns",
            example=None,
        )

        assert "Focus on service patterns" in prompt
        assert "Instructions:" in prompt

    def test_includes_example(self):
        """Should include example in prompt."""
        prompt = _build_llm_prompt(
            node_type="BusinessConcept",
            content="class MyService: pass",
            instruction=None,
            example='{"name": "Example"}',
        )

        assert '{"name": "Example"}' in prompt
        assert "Example output format:" in prompt


class TestCreateNodeFromData:
    """Tests for _create_node_from_data function."""

    def test_creates_business_concept_node(self):
        """Should create BusinessConceptNode from data."""
        node_data = {
            "properties": {
                "name": "UserAuth",
                "concept_type": "service",
                "description": "User authentication service",
                "origin_source": "auth.py",
            }
        }

        node = _create_node_from_data("BusinessConcept", node_data, "myrepo")

        assert node is not None
        assert node.name == "UserAuth"
        assert node.concept_type == "service"
        assert node.repository_name == "myrepo"
        assert node.extraction_method == "llm"  # default

    def test_creates_node_with_custom_extraction_method(self):
        """Should create node with custom extraction method."""
        node_data = {
            "properties": {
                "name": "UserAuth",
                "concept_type": "service",
                "description": "User authentication service",
                "origin_source": "auth.py",
            }
        }

        node = _create_node_from_data("BusinessConcept", node_data, "myrepo", extraction_method="ast")

        assert node is not None
        assert node.extraction_method == "ast"

    def test_creates_type_definition_node(self):
        """Should create TypeDefinitionNode from data."""
        node_data = {
            "properties": {
                "name": "UserModel",
                "type_category": "class",
                "file_path": "models/user.py",
                "description": "User model",
            }
        }

        node = _create_node_from_data("TypeDefinition", node_data, "myrepo")

        assert node is not None
        assert node.name == "UserModel"
        assert node.type_category == "class"
        assert node.extraction_method == "llm"  # default when called directly

    def test_creates_type_definition_with_ast_method(self):
        """Should create TypeDefinitionNode with AST extraction method."""
        node_data = {
            "properties": {
                "name": "UserModel",
                "type_category": "class",
                "file_path": "models/user.py",
                "description": "User model",
            }
        }

        node = _create_node_from_data("TypeDefinition", node_data, "myrepo", extraction_method="ast")

        assert node is not None
        assert node.extraction_method == "ast"

    def test_creates_method_node(self):
        """Should create MethodNode from data."""
        node_data = {
            "properties": {
                "name": "get_user",
                "return_type": "User",
                "visibility": "public",
                "file_path": "api.py",
                "type_name": "UserService",
            }
        }

        node = _create_node_from_data("Method", node_data, "myrepo")

        assert node is not None
        assert node.name == "get_user"
        assert node.return_type == "User"

    def test_creates_technology_node(self):
        """Should create TechnologyNode from data."""
        node_data = {
            "properties": {
                "name": "PostgreSQL",
                "tech_category": "system_software",
                "description": "Database",
            }
        }

        node = _create_node_from_data("Technology", node_data, "myrepo")

        assert node is not None
        assert node.name == "PostgreSQL"
        assert node.tech_category == "system_software"

    def test_creates_external_dependency_node(self):
        """Should create ExternalDependencyNode from data."""
        node_data = {
            "properties": {
                "name": "requests",
                "dependency_category": "library",
                "version": "2.28.0",
            }
        }

        node = _create_node_from_data("ExternalDependency", node_data, "myrepo")

        assert node is not None
        assert node.name == "requests"
        assert node.dependency_category == "library"

    def test_creates_test_node(self):
        """Should create TestNode from data."""
        node_data = {
            "properties": {
                "name": "test_login",
                "test_type": "unit",
                "file_path": "tests/test_auth.py",
            }
        }

        node = _create_node_from_data("Test", node_data, "myrepo")

        assert node is not None
        assert node.name == "test_login"
        assert node.test_type == "unit"

    def test_returns_none_for_unknown_type(self):
        """Should return None for unknown node type."""
        node = _create_node_from_data("UnknownType", {}, "myrepo")

        assert node is None

    def test_handles_alternate_property_names(self):
        """Should handle alternate property names for compatibility."""
        # ExternalDependency with dependencyName instead of name
        node_data = {
            "properties": {
                "dependencyName": "axios",
                "dependencyCategory": "library",
            }
        }

        node = _create_node_from_data("ExternalDependency", node_data, "myrepo")

        assert node is not None
        assert node.name == "axios"

    def test_handles_missing_properties(self):
        """Should handle missing properties with defaults."""
        node_data = {
            "properties": {
                "name": "TestConcept",
            }
        }

        node = _create_node_from_data("BusinessConcept", node_data, "myrepo")

        assert node is not None
        assert node.name == "TestConcept"
        assert node.concept_type == "other"  # default
        assert node.description == ""


class TestRunExtractionStep:
    """Tests for _run_extraction_step function."""

    def test_dispatches_to_repository_extraction(self):
        """Should dispatch Repository type to repository extractor."""
        mock_cfg = MagicMock()
        mock_cfg.node_type = "Repository"

        mock_repo = MagicMock()
        mock_repo.name = "test"
        mock_repo.url = "https://example.com/repo.git"
        mock_repo.branch = "main"

        graph_manager = MagicMock()

        result = _run_extraction_step(
            cfg=mock_cfg,
            repo=mock_repo,
            repo_path=Path("/tmp"),
            classified_files=[],
            undefined_files=[],
            graph_manager=graph_manager,
            llm_query_fn=None,
            engine=MagicMock(),
        )

        assert "nodes_created" in result

    def test_dispatches_to_directory_extraction(self):
        """Should dispatch Directory type to directory extractor."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "src").mkdir()

            mock_cfg = MagicMock()
            mock_cfg.node_type = "Directory"

            mock_repo = MagicMock()
            mock_repo.name = "test"

            graph_manager = MagicMock()

            result = _run_extraction_step(
                cfg=mock_cfg,
                repo=mock_repo,
                repo_path=Path(tmpdir),
                classified_files=[],
                undefined_files=[],
                graph_manager=graph_manager,
                llm_query_fn=None,
                engine=MagicMock(),
            )

            assert "nodes_created" in result

    def test_dispatches_to_file_extraction(self):
        """Should dispatch File type to file extractor."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("def main(): pass")

            mock_cfg = MagicMock()
            mock_cfg.node_type = "File"

            mock_repo = MagicMock()
            mock_repo.name = "test"

            graph_manager = MagicMock()

            result = _run_extraction_step(
                cfg=mock_cfg,
                repo=mock_repo,
                repo_path=Path(tmpdir),
                classified_files=[],
                undefined_files=[],
                graph_manager=graph_manager,
                llm_query_fn=None,
                engine=MagicMock(),
            )

            assert "nodes_created" in result

    def test_requires_llm_for_business_concept(self):
        """Should require LLM for BusinessConcept extraction."""
        mock_cfg = MagicMock()
        mock_cfg.node_type = "BusinessConcept"

        result = _run_extraction_step(
            cfg=mock_cfg,
            repo=MagicMock(),
            repo_path=Path("/tmp"),
            classified_files=[],
            undefined_files=[],
            graph_manager=MagicMock(),
            llm_query_fn=None,  # No LLM provided
            engine=MagicMock(),
        )

        assert result["nodes_created"] == 0
        assert any("LLM required" in str(e) for e in result["errors"])

    def test_handles_unknown_node_type(self):
        """Should handle unknown node type."""
        mock_cfg = MagicMock()
        mock_cfg.node_type = "UnknownType"

        result = _run_extraction_step(
            cfg=mock_cfg,
            repo=MagicMock(),
            repo_path=Path("/tmp"),
            classified_files=[],
            undefined_files=[],
            graph_manager=MagicMock(),
            llm_query_fn=None,
            engine=MagicMock(),
        )

        assert any("Unknown node type" in str(e) for e in result["errors"])


class TestRunExtractionWithRunLogger:
    """Tests for run_extraction with run_logger."""

    def test_logs_phase_start_and_complete(self):
        """Should log phase start and completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()
            run_logger = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "Repository"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        run_extraction(engine, graph_manager, run_logger=run_logger)

            run_logger.phase_start.assert_called_once()
            run_logger.phase_complete.assert_called_once()

    def test_logs_phase_error_on_failure(self):
        """Should log phase error when errors occur."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()
            run_logger = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "UnknownType"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        run_extraction(engine, graph_manager, run_logger=run_logger)

            run_logger.phase_error.assert_called_once()

    def test_logs_step_start_and_complete(self):
        """Should log step start and completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()
            run_logger = MagicMock()
            step_ctx = MagicMock()
            run_logger.step_start.return_value = step_ctx

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "Repository"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        run_extraction(engine, graph_manager, run_logger=run_logger)

            run_logger.step_start.assert_called()
            step_ctx.complete.assert_called()


class TestRunExtractionWithProgressReporter:
    """Tests for run_extraction with progress reporter."""

    def test_calls_progress_methods(self):
        """Should call progress reporter methods."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()
            progress = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "Repository"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        run_extraction(engine, graph_manager, progress=progress)

            progress.start_phase.assert_called_once()
            progress.complete_phase.assert_called_once()

    def test_logs_step_progress(self):
        """Should log step start and completion via progress."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()
            progress = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "Repository"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        run_extraction(engine, graph_manager, progress=progress)

            progress.start_step.assert_called()
            progress.complete_step.assert_called()


class TestRunExtractionVerbose:
    """Tests for run_extraction with verbose output."""

    def test_prints_repository_name(self, capsys):
        """Should print repository name in verbose mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "verbose_test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "Repository"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        run_extraction(engine, graph_manager, verbose=True)

            captured = capsys.readouterr()
            assert "verbose_test_repo" in captured.out

    def test_prints_extraction_step(self, capsys):
        """Should print extraction step name in verbose mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "Repository"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        run_extraction(engine, graph_manager, verbose=True)

            captured = capsys.readouterr()
            assert "Extracting:" in captured.out or "Repository" in captured.out


class TestRunExtractionConfigVersions:
    """Tests for run_extraction with config_versions."""

    def test_uses_versioned_configs(self):
        """Should use versioned config lookup when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "Repository"

            config_versions = {
                "extraction": {
                    "Repository": 2,
                    "File": 3,
                }
            }

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs_by_version") as mock_version:
                    mock_version.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        run_extraction(engine, graph_manager, config_versions=config_versions)

            mock_version.assert_called_once()


class TestRunExtractionClassifyOnlyPhase:
    """Tests for run_extraction classify-only mode."""

    def test_classify_only_skips_parse(self, capsys):
        """Should skip parse phase when phases=['classify']."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("def main(): pass")

            engine = MagicMock()
            graph_manager = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "Repository"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = [MagicMock(extension=".py", file_type="source", subtype="python")]

                        result = run_extraction(engine, graph_manager, phases=["classify"], verbose=True)

            captured = capsys.readouterr()
            assert "Skipping parse phase" in captured.out
            assert result["stats"]["steps_completed"] >= 1

    def test_classify_counts_files(self):
        """Should track classification stats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("def main(): pass")
            (Path(tmpdir) / "config.xyz").write_text("unknown")

            engine = MagicMock()
            graph_manager = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [MagicMock(node_type="Repository")]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = [MagicMock(extension=".py", file_type="source", subtype="python")]

                        result = run_extraction(engine, graph_manager, phases=["classify"])

            assert "files_classified" in result["stats"]


class TestRunExtractionIter:
    """Tests for run_extraction_iter generator function."""

    def test_yields_progress_updates(self):
        """Should yield ProgressUpdate objects."""
        from deriva.common.types import ProgressUpdate
        from deriva.services.extraction import run_extraction_iter

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "Repository"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        updates = list(run_extraction_iter(engine, graph_manager))

            assert len(updates) >= 1
            assert all(isinstance(u, ProgressUpdate) for u in updates)

    def test_yields_error_when_no_repos(self):
        """Should yield error when no repositories found."""
        from deriva.services.extraction import run_extraction_iter

        engine = MagicMock()
        graph_manager = MagicMock()

        with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
            mock_repo_mgr.return_value.list_repositories.return_value = []

            updates = list(run_extraction_iter(engine, graph_manager))

        assert len(updates) == 1
        assert updates[0].status == "error"
        assert "No repositories found" in updates[0].message

    def test_yields_error_when_no_configs(self):
        """Should yield error when no configs enabled."""
        from deriva.services.extraction import run_extraction_iter

        engine = MagicMock()
        graph_manager = MagicMock()

        mock_repo = MagicMock()
        mock_repo.name = "test"
        mock_repo.path = "/tmp"

        with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
            mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

            with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                mock_cfg.return_value = []

                updates = list(run_extraction_iter(engine, graph_manager))

        assert len(updates) == 1
        assert updates[0].status == "error"
        assert "No extraction configs enabled" in updates[0].message

    def test_yields_step_complete_for_each_step(self):
        """Should yield step complete for each extraction step."""
        from deriva.services.extraction import run_extraction_iter

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config1 = MagicMock()
            mock_config1.node_type = "Repository"
            mock_config2 = MagicMock()
            mock_config2.node_type = "Directory"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config1, mock_config2]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        updates = list(run_extraction_iter(engine, graph_manager))

            step_updates = [u for u in updates if u.step]
            assert len(step_updates) >= 2

    def test_yields_error_on_step_exception(self):
        """Should yield error when step raises exception."""
        from deriva.services.extraction import run_extraction_iter

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            graph_manager = MagicMock()

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"
            mock_repo.path = tmpdir
            mock_repo.url = "https://example.com/repo.git"
            mock_repo.branch = "main"

            mock_config = MagicMock()
            mock_config.node_type = "Repository"

            with patch("deriva.services.extraction.RepoManager") as mock_repo_mgr:
                mock_repo_mgr.return_value.list_repositories.return_value = [mock_repo]

                with patch("deriva.services.extraction.config.get_extraction_configs") as mock_cfg:
                    mock_cfg.return_value = [mock_config]

                    with patch("deriva.services.extraction.config.get_file_types") as mock_ft:
                        mock_ft.return_value = []

                        with patch("deriva.services.extraction._run_extraction_step", side_effect=Exception("Test error")):
                            updates = list(run_extraction_iter(engine, graph_manager))

            error_updates = [u for u in updates if u.status == "error"]
            assert len(error_updates) >= 1


class TestExtractEdges:
    """Tests for edge extraction functions."""

    def test_extract_edges_unified(self):
        """Should extract edges using unified batch extraction."""
        from deriva.services.extraction import _extract_edges

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("import os\n\ndef hello(): pass")

            mock_repo = MagicMock()
            mock_repo.name = "test_repo"

            classified_files = [{"path": "main.py", "file_type": "source", "subtype": "python"}]

            graph_manager = MagicMock()
            graph_manager.get_nodes_by_type.return_value = []
            graph_manager.node_exists.return_value = True
            graph_manager.add_edge.return_value = "edge_1"

            with patch("deriva.modules.extraction.edges.extract_edges_batch") as mock_batch:
                mock_batch.return_value = {
                    "data": {"edges": []},
                    "stats": {},
                    "errors": [],
                }

                result = _extract_edges(mock_repo, Path(tmpdir), classified_files, graph_manager)

            assert "edges_created" in result
            mock_batch.assert_called_once()


class TestExtractImports:
    """Tests for _extract_imports function."""

    def test_calls_extract_edges_with_import_types(self):
        """Should call _extract_edges with IMPORTS and USES edge types."""
        from deriva.services.extraction import _extract_imports

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_repo = MagicMock()
            mock_repo.name = "test"

            graph_manager = MagicMock()
            graph_manager.get_nodes_by_type.return_value = []

            with patch("deriva.services.extraction._extract_edges") as mock_extract:
                mock_extract.return_value = {"edges_created": 0, "errors": []}

                _extract_imports(mock_repo, Path(tmpdir), [], graph_manager)

            mock_extract.assert_called_once()
            # Check that edge_types parameter was passed
            call_args = mock_extract.call_args
            assert call_args[0][4] is not None  # edge_types set


class TestExtractCalls:
    """Tests for _extract_calls function."""

    def test_calls_extract_edges_with_calls_type(self):
        """Should call _extract_edges with CALLS edge type."""
        from deriva.services.extraction import _extract_calls

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_repo = MagicMock()
            mock_repo.name = "test"

            graph_manager = MagicMock()
            graph_manager.get_nodes_by_type.return_value = []

            with patch("deriva.services.extraction._extract_edges") as mock_extract:
                mock_extract.return_value = {"edges_created": 0, "errors": []}

                _extract_calls(mock_repo, Path(tmpdir), [], graph_manager)

            mock_extract.assert_called_once()


class TestExtractDecorators:
    """Tests for _extract_decorators function."""

    def test_calls_extract_edges_with_decorated_by_type(self):
        """Should call _extract_edges with DECORATED_BY edge type."""
        from deriva.services.extraction import _extract_decorators

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_repo = MagicMock()
            mock_repo.name = "test"

            graph_manager = MagicMock()
            graph_manager.get_nodes_by_type.return_value = []

            with patch("deriva.services.extraction._extract_edges") as mock_extract:
                mock_extract.return_value = {"edges_created": 0, "errors": []}

                _extract_decorators(mock_repo, Path(tmpdir), [], graph_manager)

            mock_extract.assert_called_once()


class TestExtractReferences:
    """Tests for _extract_references function."""

    def test_calls_extract_edges_with_references_type(self):
        """Should call _extract_edges with REFERENCES edge type."""
        from deriva.services.extraction import _extract_references

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_repo = MagicMock()
            mock_repo.name = "test"

            graph_manager = MagicMock()
            graph_manager.get_nodes_by_type.return_value = []

            with patch("deriva.services.extraction._extract_edges") as mock_extract:
                mock_extract.return_value = {"edges_created": 0, "errors": []}

                _extract_references(mock_repo, Path(tmpdir), [], graph_manager)

            mock_extract.assert_called_once()


class TestExtractDirectoryClassification:
    """Tests for _extract_directory_classification function."""

    def test_queries_directories_from_graph(self):
        """Should query directories from graph."""
        from deriva.services.extraction import _extract_directory_classification

        mock_cfg = MagicMock()
        mock_cfg.instruction = "Classify directories"
        mock_cfg.example = "{}"
        mock_cfg.temperature = None
        mock_cfg.max_tokens = None
        mock_cfg.batch_size = 50

        mock_repo = MagicMock()
        mock_repo.name = "test_repo"

        graph_manager = MagicMock()
        graph_manager.query.return_value = []

        result = _extract_directory_classification(mock_cfg, mock_repo, graph_manager, MagicMock())

        graph_manager.query.assert_called_once()
        assert result["nodes_created"] == 0

    def test_handles_query_exception(self):
        """Should handle query exception gracefully."""
        from deriva.services.extraction import _extract_directory_classification

        mock_cfg = MagicMock()
        mock_cfg.instruction = "Classify"
        mock_cfg.example = "{}"

        mock_repo = MagicMock()
        mock_repo.name = "test_repo"

        graph_manager = MagicMock()
        graph_manager.query.side_effect = Exception("DB error")

        result = _extract_directory_classification(mock_cfg, mock_repo, graph_manager, MagicMock())

        assert result["nodes_created"] == 0
        assert "Failed to query directories" in result["errors"][0]

    def test_classifies_directories_with_llm(self):
        """Should classify directories using LLM."""
        from deriva.services.extraction import _extract_directory_classification

        mock_cfg = MagicMock()
        mock_cfg.instruction = "Classify directories"
        mock_cfg.example = "{}"
        mock_cfg.temperature = None
        mock_cfg.max_tokens = None
        mock_cfg.batch_size = 50

        mock_repo = MagicMock()
        mock_repo.name = "test_repo"

        graph_manager = MagicMock()
        graph_manager.query.return_value = [
            {"name": "src", "path": "src", "id": "dir_1"},
            {"name": "tests", "path": "tests", "id": "dir_2"},
        ]

        with patch("deriva.services.extraction.classify_directories") as mock_classify:
            mock_classify.return_value = {
                "success": True,
                "data": {
                    "nodes": [
                        {
                            "id": "bc_1",
                            "labels": ["Graph:BusinessConcept"],
                            "properties": {
                                "conceptName": "SourceCode",
                                "conceptType": "entity",
                                "description": "Source code directory",
                            },
                        }
                    ],
                    "edges": [],
                },
            }

            result = _extract_directory_classification(mock_cfg, mock_repo, graph_manager, MagicMock())

        assert result["nodes_created"] >= 1
        graph_manager.add_node.assert_called()


class TestExtractFileContentWithChunking:
    """Tests for _extract_file_content with chunking."""

    def test_chunks_large_content(self):
        """Should chunk large content."""
        # Create content large enough to require chunking
        content = "def func():\n    pass\n" * 1000

        def mock_extract_fn(_file_path, _content, _repo_name, _llm_fn, _config):
            return {
                "success": True,
                "data": {
                    "nodes": [{"properties": {"name": "func"}}],
                    "edges": [],
                },
            }

        with patch("deriva.services.extraction.should_chunk", return_value=True):
            with patch("deriva.services.extraction.chunk_content") as mock_chunk:
                from deriva.common.chunking import Chunk

                mock_chunk.return_value = [
                    Chunk(content="def func(): pass", index=0, total=2, start_line=1, end_line=10),
                    Chunk(content="def func2(): pass", index=1, total=2, start_line=11, end_line=20),
                ]

                _nodes, _edges, _errors = _extract_file_content(
                    file_path="large.py",
                    content=content,
                    repo_name="myrepo",
                    extract_fn=mock_extract_fn,
                    extraction_config={},
                    llm_query_fn=MagicMock(),
                )

        assert mock_chunk.called

    def test_passes_existing_concepts_to_extract_fn(self):
        """Should pass existing_concepts when provided."""
        content = "def func(): pass"
        existing_concepts = [{"conceptName": "TestConcept", "conceptType": "entity"}]

        extract_calls = []

        def mock_extract_fn(file_path, content, repo_name, llm_fn, config, existing_concepts=None):
            extract_calls.append(existing_concepts)
            return {
                "success": True,
                "data": {"nodes": [], "edges": []},
            }

        nodes, edges, errors = _extract_file_content(
            file_path="test.py",
            content=content,
            repo_name="myrepo",
            extract_fn=mock_extract_fn,
            extraction_config={},
            llm_query_fn=MagicMock(),
            existing_concepts=existing_concepts,
        )

        assert len(extract_calls) == 1
        assert extract_calls[0] == existing_concepts


class TestExtractLLMBasedBatching:
    """Tests for _extract_llm_based with batching."""

    def test_uses_batching_for_business_concepts(self):
        """Should use batching when batch_size > 1 for BusinessConcept."""
        import json as json_module

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple files
            (Path(tmpdir) / "file1.py").write_text("class A: pass")
            (Path(tmpdir) / "file2.py").write_text("class B: pass")

            mock_cfg = MagicMock()
            mock_cfg.node_type = "BusinessConcept"
            mock_cfg.input_sources = json_module.dumps({"files": [{"type": "source", "subtype": "python"}]})
            mock_cfg.instruction = "Extract concepts"
            mock_cfg.example = "{}"
            mock_cfg.batch_size = 10  # Enable batching
            mock_cfg.temperature = None
            mock_cfg.max_tokens = None

            mock_repo = MagicMock()
            mock_repo.name = "test"

            classified_files = [
                {"path": "file1.py", "file_type": "source", "subtype": "python"},
                {"path": "file2.py", "file_type": "source", "subtype": "python"},
            ]

            graph_manager = MagicMock()

            with patch("deriva.services.extraction.extraction.extract_business_concepts_multi") as mock_multi:
                mock_multi.return_value = {
                    "success": True,
                    "data": {"nodes": [], "edges": []},
                    "errors": [],
                }

                _extract_llm_based(
                    node_type="BusinessConcept",
                    cfg=mock_cfg,
                    repo=mock_repo,
                    repo_path=Path(tmpdir),
                    classified_files=classified_files,
                    graph_manager=graph_manager,
                    llm_query_fn=MagicMock(),
                    engine=MagicMock(),
                )

            mock_multi.assert_called()


class TestExtractLLMBasedTreesitter:
    """Tests for _extract_llm_based with tree-sitter extraction."""

    def test_uses_treesitter_for_type_definition(self):
        """Should use tree-sitter for TypeDefinition on Python files."""
        import json as json_module

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("class MyClass:\n    pass")

            mock_cfg = MagicMock()
            mock_cfg.node_type = "TypeDefinition"
            mock_cfg.input_sources = json_module.dumps({"files": [{"type": "source", "subtype": "python"}]})
            mock_cfg.instruction = "Extract types"
            mock_cfg.example = "{}"
            mock_cfg.batch_size = 1

            mock_repo = MagicMock()
            mock_repo.name = "test"

            classified_files = [
                {"path": "main.py", "file_type": "source", "subtype": "python"},
            ]

            graph_manager = MagicMock()

            with patch("deriva.services.extraction.extraction.extract_types_from_source") as mock_ts:
                mock_ts.return_value = {
                    "success": True,
                    "data": {
                        "nodes": [{"properties": {"name": "MyClass", "type_category": "class"}}],
                        "edges": [],
                    },
                }

                result = _extract_llm_based(
                    node_type="TypeDefinition",
                    cfg=mock_cfg,
                    repo=mock_repo,
                    repo_path=Path(tmpdir),
                    classified_files=classified_files,
                    graph_manager=graph_manager,
                    llm_query_fn=MagicMock(),
                    engine=MagicMock(),
                )

            mock_ts.assert_called()
            assert result["nodes_created"] >= 1

    def test_uses_treesitter_for_method(self):
        """Should use tree-sitter for Method on Python files."""
        import json as json_module

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("def my_func():\n    pass")

            mock_cfg = MagicMock()
            mock_cfg.node_type = "Method"
            mock_cfg.input_sources = json_module.dumps({"files": [{"type": "source", "subtype": "python"}]})
            mock_cfg.instruction = "Extract methods"
            mock_cfg.example = "{}"
            mock_cfg.batch_size = 1

            mock_repo = MagicMock()
            mock_repo.name = "test"

            classified_files = [
                {"path": "main.py", "file_type": "source", "subtype": "python"},
            ]

            graph_manager = MagicMock()

            with patch("deriva.services.extraction.extraction.extract_methods_from_source") as mock_ts:
                mock_ts.return_value = {
                    "success": True,
                    "data": {
                        "nodes": [{"properties": {"name": "my_func"}}],
                        "edges": [],
                    },
                }

                _extract_llm_based(
                    node_type="Method",
                    cfg=mock_cfg,
                    repo=mock_repo,
                    repo_path=Path(tmpdir),
                    classified_files=classified_files,
                    graph_manager=graph_manager,
                    llm_query_fn=MagicMock(),
                    engine=MagicMock(),
                )

            mock_ts.assert_called()


class TestExtractEdgesCreateStubNodes:
    """Tests for edge extraction creating stub nodes."""

    def test_creates_stub_external_dependency_for_uses_edge(self):
        """Should create stub ExternalDependency node for USES edges."""
        from deriva.services.extraction import _extract_edges

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_repo = MagicMock()
            mock_repo.name = "test_repo"

            classified_files = []

            graph_manager = MagicMock()
            graph_manager.get_nodes_by_type.return_value = []
            graph_manager.node_exists.return_value = False  # Node doesn't exist
            graph_manager.add_edge.return_value = "edge_1"

            with patch("deriva.modules.extraction.edges.extract_edges_batch") as mock_batch:
                mock_batch.return_value = {
                    "data": {
                        "nodes": [
                            {
                                "node_id": "extdep::test_repo::requests",
                                "label": "ExternalDependency",
                                "properties": {
                                    "dependencyName": "requests",
                                    "dependencyCategory": "library",
                                    "declared": False,
                                    "used": True,
                                    "ecosystem": "pypi",
                                },
                            }
                        ],
                        "edges": [
                            {
                                "from_node_id": "file_1",
                                "to_node_id": "extdep::test_repo::requests",
                                "relationship_type": "USES",
                            }
                        ],
                    },
                    "stats": {},
                    "errors": [],
                }

                result = _extract_edges(mock_repo, Path(tmpdir), classified_files, graph_manager)

            # Should have created a stub node
            graph_manager.add_node.assert_called()
            assert result["nodes_created"] >= 1
