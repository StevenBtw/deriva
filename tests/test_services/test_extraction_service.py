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

            result = _extract_files(mock_repo, Path(tmpdir), classified_files, graph_manager)

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
            graph_manager=MagicMock(),
            llm_query_fn=None,
            engine=MagicMock(),
        )

        assert any("Unknown node type" in str(e) for e in result["errors"])
