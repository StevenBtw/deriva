"""Tests for services.extraction module."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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


@pytest.fixture(autouse=True)
def default_excluded_directories():
    """Most tests use a bare MagicMock engine; give the walk the default exclusion list."""
    from deriva.services import config

    with patch.object(config, "get_excluded_directories", return_value=list(config.DEFAULT_EXCLUDED_DIRECTORIES)):
        yield


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

            result = _extract_directories(mock_repo, Path(tmpdir), graph_manager, [".git"])

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

            result = _extract_files(mock_repo, Path(tmpdir), classified_files, [], graph_manager, [".git"])

            assert result["nodes_created"] >= 1
            graph_manager.add_node.assert_called()


class TestStructuralStepsWithoutLLM:
    """--no-llm: TypeDefinition, Method and ExternalDependency still parse what tree-sitter and the manifest parsers read."""

    @staticmethod
    def _cfg(node_type: str, subtype: str) -> MagicMock:
        import json as json_module

        cfg = MagicMock()
        cfg.node_type = node_type
        cfg.input_sources = json_module.dumps({"files": [{"type": "source", "subtype": subtype}]})
        cfg.params = None
        cfg.instruction = ""
        cfg.example = ""
        return cfg

    @staticmethod
    def _run(cfg: MagicMock, tmpdir: str, files: list[dict]) -> dict:
        repo = MagicMock()
        repo.name = "myproject"
        return _run_extraction_step(
            cfg=cfg,
            repo=repo,
            repo_path=Path(tmpdir),
            classified_files=files,
            undefined_files=[],
            graph_manager=MagicMock(),
            llm_query_fn=None,
            engine=MagicMock(),
        )

    def test_type_definitions_come_from_tree_sitter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "service.py").write_text("class OrderService:\n    pass\n", encoding="utf-8")
            result = self._run(self._cfg("TypeDefinition", "python"), tmpdir, [{"path": "service.py", "file_type": "source", "subtype": "python"}])

        assert result["nodes_created"] >= 1
        assert not any("LLM required" in e for e in result["errors"])

    def test_files_without_a_parser_are_skipped_with_a_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "batch.pas").write_text("program Batch;\n", encoding="utf-8")
            result = self._run(self._cfg("TypeDefinition", "pascal"), tmpdir, [{"path": "batch.pas", "file_type": "source", "subtype": "pascal"}])

        assert result["nodes_created"] == 0
        assert result["errors"] == ["LLM required for TypeDefinition in 1 file without a parser (skipped)"]

    def test_external_dependencies_come_from_the_manifest_parsers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
            result = self._run(self._cfg("ExternalDependency", "requirements"), tmpdir, [{"path": "requirements.txt", "file_type": "source", "subtype": "requirements"}])

        assert result["nodes_created"] >= 1
        assert not any("LLM required" in e for e in result["errors"])


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
        mock_cfg.params = None
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
            mock_cfg.node_type = "Test"
            # Use proper JSON format for input_sources
            mock_cfg.input_sources = json_module.dumps({"files": [{"type": "source", "subtype": "python"}]})
            mock_cfg.params = None
            mock_cfg.instruction = "Extract tests"
            mock_cfg.example = None
            mock_cfg.batch_size = 1

            mock_repo = MagicMock()
            mock_repo.name = "myproject"

            classified_files = [
                {"path": "main.py", "file_type": "source", "subtype": "python"},
            ]

            graph_manager = MagicMock()

            with patch("deriva.services.extraction._extract_file_content") as mock_extract:
                mock_extract.return_value = (
                    [{"properties": {"name": "test_my_service", "test_type": "unit", "file_path": "main.py"}}],
                    [],
                    [],
                )

                result = _extract_llm_based(
                    node_type="Test",
                    cfg=mock_cfg,
                    repo=mock_repo,
                    repo_path=Path(tmpdir),
                    classified_files=classified_files,
                    graph_manager=graph_manager,
                    llm_query_fn=MagicMock(),
                    engine=MagicMock(),
                )

            assert result["nodes_created"] >= 1

    def test_edge_properties_are_persisted(self):
        """Edge properties from the module reach the graph."""
        import json as json_module

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "manifest.txt").write_text("x")
            cfg = SimpleNamespace(
                node_type="Test",
                input_sources=json_module.dumps({"files": [{"type": "config", "subtype": "text"}]}),
                params=None,
                instruction="I",
                example=None,
                batch_size=1,
            )
            repo = SimpleNamespace(name="r")
            graph_manager = MagicMock()
            graph_manager.node_exists.return_value = True
            edge = {"from_node_id": "file::r::manifest.txt", "to_node_id": "test::r::alpha", "relationship_type": "TESTS", "properties": {"route": "llm"}}

            with patch("deriva.services.extraction._extract_file_content", return_value=([], [edge], [])):
                _extract_llm_based(
                    node_type="Test",
                    cfg=cfg,
                    repo=repo,
                    repo_path=Path(tmpdir),
                    classified_files=[{"path": "manifest.txt", "file_type": "config", "subtype": "text"}],
                    graph_manager=graph_manager,
                    llm_query_fn=MagicMock(),
                    engine=MagicMock(),
                )

            graph_manager.add_edge.assert_called_once_with(src_id="file::r::manifest.txt", dst_id="test::r::alpha", relationship="TESTS", properties={"route": "llm"})


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

    def test_annotations_of_types_and_methods_are_kept(self):
        """Annotations and decorators are structure later steps select on (an endpoint marker, a route)."""
        type_props = {"typeName": "OrderController", "category": "class", "filePath": "a.java", "decorators": ["RestController"]}
        method_props = {"methodName": "find", "typeName": "OrderController", "filePath": "a.java", "decorators": ['GetMapping("orders")']}
        type_node = _create_node_from_data("TypeDefinition", {"properties": type_props}, "r", extraction_method="ast")
        method_node = _create_node_from_data("Method", {"properties": method_props}, "r", extraction_method="ast")

        assert type_node.to_dict()["decorators"] == ["RestController"]
        assert method_node.to_dict()["decorators"] == ['GetMapping("orders")']
        assert _create_node_from_data("TypeDefinition", {"properties": {"typeName": "Plain"}}, "r").to_dict()["decorators"] == []

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

    def test_step_stats_reach_the_run_log(self, tmp_path):
        """A step that reports stats (selection sizes, label counts) has them logged with its completion."""
        run_logger = MagicMock()
        step_ctx = MagicMock()
        run_logger.step_start.return_value = step_ctx
        repo = SimpleNamespace(name="test_repo", path=str(tmp_path), url="u", branch="main")
        step_result = {"nodes_created": 0, "edges_created": 0, "errors": [], "stats": {"selected": 3}}

        with (
            patch("deriva.services.extraction.RepoManager") as repo_mgr,
            patch("deriva.services.extraction.config.get_extraction_configs", return_value=[SimpleNamespace(node_type="Repository", extraction_method="structural")]),
            patch("deriva.services.extraction.config.get_file_types", return_value=[]),
            patch("deriva.services.extraction._run_extraction_step", return_value=step_result),
        ):
            repo_mgr.return_value.list_repositories.return_value = [repo]
            run_extraction(MagicMock(), MagicMock(), run_logger=run_logger)

        assert step_ctx.stats == {"selected": 3}
        step_ctx.complete.assert_called_once()

    def test_step_stats_are_returned_per_repository_and_step(self, tmp_path):
        """Callers (the step benchmark) read a step's own report from the result."""
        repo = SimpleNamespace(name="test_repo", path=str(tmp_path), url="u", branch="main")
        step_result = {"nodes_created": 0, "edges_created": 0, "errors": [], "stats": {"selected": 3}}

        with (
            patch("deriva.services.extraction.RepoManager") as repo_mgr,
            patch("deriva.services.extraction.config.get_extraction_configs", return_value=[SimpleNamespace(node_type="Repository", extraction_method="structural")]),
            patch("deriva.services.extraction.config.get_file_types", return_value=[]),
            patch("deriva.services.extraction._run_extraction_step", return_value=step_result),
        ):
            repo_mgr.return_value.list_repositories.return_value = [repo]
            result = run_extraction(MagicMock(), MagicMock())

        assert result["step_stats"] == {"test_repo": {"Repository": {"selected": 3}}}


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

    def test_lookups_carry_repo_relative_paths_so_the_same_file_is_preferred(self):
        """The graph stores repo-prefixed paths; the files being parsed are repo-relative, so the lookups drop the prefix."""
        from deriva.services.extraction import _extract_edges

        mock_repo = MagicMock()
        mock_repo.name = "shop"
        nodes = {
            "Method": [{"id": "m1", "properties": {"methodName": "run", "typeName": "", "filePath": "shop/shop/jobs.py"}}],
            "TypeDefinition": [{"id": "t1", "properties": {"typeName": "Order", "filePath": "shop/orders/model.py"}}],
        }
        graph_manager = MagicMock()
        graph_manager.get_nodes_by_type.side_effect = lambda node_type: nodes.get(node_type, [])

        with patch("deriva.modules.extraction.edges.extract_edges_batch") as mock_batch:
            mock_batch.return_value = {"data": {"edges": []}, "stats": {}, "errors": []}
            _extract_edges(mock_repo, Path("."), [], graph_manager)

        kwargs = mock_batch.call_args.kwargs
        assert kwargs["global_method_lookup"][("run", None)][0]["file_path"] == "shop/jobs.py"
        assert kwargs["global_type_lookup"]["Order"][0]["file_path"] == "orders/model.py"

    def test_the_calls_step_passes_its_cross_language_calls_and_module_roots(self):
        """Calls params: ``call_languages`` (caller language -> callee languages it may call) and ``module_files``
        (a folder holding one is a module root; a call without an import stays within its module root)."""
        from deriva.services.extraction import _run_step_writes

        params = {"call_languages": {"jcl": ["cobol"]}, "module_files": ["pom.xml", "Dockerfile*"]}
        cfg = SimpleNamespace(node_type="Calls", params=json.dumps(params))
        files = [{"path": p} for p in ("svc/pom.xml", "svc/src/A.java", "svc/web/Dockerfile.web", "svc/web/app.js", "app/cbl/A.cbl")]
        graph_manager = MagicMock()
        graph_manager.get_nodes_by_type.return_value = []
        with patch("deriva.modules.extraction.edges.extract_edges_batch") as mock_batch:
            mock_batch.return_value = {"data": {"edges": []}, "stats": {}, "errors": []}
            _run_step_writes(cfg, SimpleNamespace(name="r"), Path("."), files, [], graph_manager, None, MagicMock())

        kwargs = mock_batch.call_args.kwargs
        assert kwargs["call_languages"] == {"jcl": frozenset({"cobol"})}
        scope = kwargs["scope_of"]
        assert (scope("svc/src/A.java"), scope("svc/web/app.js"), scope("app/cbl/A.cbl")) == ("svc", "svc/web", "")

    def test_the_calls_step_validates_its_params(self):
        from deriva.services.extraction import _run_step_writes

        cfg = SimpleNamespace(node_type="Calls", params=json.dumps({"call_languages": [["jcl", "cobol"]]}))
        with pytest.raises(ValueError, match="Calls params"):
            _run_step_writes(cfg, SimpleNamespace(name="r"), Path("."), [], [], MagicMock(), None, MagicMock())


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

                _extract_calls(SimpleNamespace(params=None), mock_repo, Path(tmpdir), [], graph_manager)

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

    def test_directories_reach_the_llm_sorted_by_path_with_their_files(self):
        """The prompt gets each directory's file counts by type and languages, in path order (real graph)."""
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager
        from deriva.adapters.graph.models import DirectoryNode, FileNode
        from deriva.services.extraction import _extract_directory_classification

        close_database()
        with GraphManager() as gm:
            for name in ("zeta", "alpha"):
                gm.add_node(DirectoryNode(name=name, path=name, repository_name="r"), node_id=f"dir::r::{name}")
            for i, (file_type, subtype) in enumerate([("source", "java"), ("source", "java"), ("docs", "markdown"), ("test", "java"), ("config", "yaml")]):
                gm.add_node(FileNode(name=f"f{i}", path=f"alpha/f{i}", repository_name="r", file_type=file_type, subtype=subtype), node_id=f"file::r::f{i}")
                gm.add_edge("dir::r::alpha", f"file::r::f{i}", "CONTAINS")
            cfg = SimpleNamespace(instruction="I", example="{}", params=None, temperature=None, max_tokens=None, batch_size=50)
            with patch("deriva.services.extraction.classify_directories", return_value={"success": True, "data": {"nodes": [], "edges": []}}) as classify:
                _extract_directory_classification(cfg, SimpleNamespace(name="r"), gm, MagicMock())
        close_database()

        alpha, zeta = classify.call_args.kwargs["directories"]
        assert (alpha["paths"], zeta["paths"]) == (["r/alpha"], ["r/zeta"])
        counts = {k: alpha[k] for k in ("file_count", "source_count", "docs_count", "test_count", "config_count")}
        assert counts == {"file_count": 5, "source_count": 2, "docs_count": 1, "test_count": 1, "config_count": 1}
        assert sorted(alpha["subtypes"]) == ["java", "markdown", "yaml"]
        assert zeta["file_count"] == 0

    def test_structural_skips_never_reach_the_llm(self):
        """Pass-through directories and configured skip names are decided before any LLM call (real graph)."""
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager
        from deriva.adapters.graph.models import DirectoryNode, FileNode
        from deriva.services.extraction import _extract_directory_classification

        close_database()
        with GraphManager() as gm:
            for path in ("r/lib", "r/lib/records", "r/utils"):
                gm.add_node(DirectoryNode(name=path.rsplit("/", 1)[-1], path=path.removeprefix("r/"), repository_name="r"), node_id=f"dir::r::{path}")
            gm.add_edge("dir::r::r/lib", "dir::r::r/lib/records", "CONTAINS")
            for path in ("r/lib/records", "r/utils"):
                gm.add_node(FileNode(name="f", path=f"{path.removeprefix('r/')}/f", repository_name="r", file_type="source", subtype="java"), node_id=f"file::r::{path}/f")
                gm.add_edge(f"dir::r::{path}", f"file::r::{path}/f", "CONTAINS")
            params = {"skip_names": ["utils"], "skip_trees": [], "skip_pass_through": True}
            cfg = SimpleNamespace(instruction="I", example="{}", params=json.dumps(params), temperature=None, max_tokens=None, batch_size=50)
            with patch("deriva.services.extraction.classify_directories", return_value={"success": True, "data": {"nodes": [], "edges": []}}) as classify:
                _extract_directory_classification(cfg, SimpleNamespace(name="r"), gm, MagicMock())
        close_database()

        (only,) = classify.call_args.kwargs["directories"]
        assert only["paths"] == ["r/lib/records"]

    @pytest.mark.parametrize("params, name", [({"skip_repository_name": True}, "r"), ({}, "")])
    def test_the_repository_name_reaches_the_classifier_when_configured(self, params, name):
        """params.skip_repository_name: a technology answer for a directory named after the repository is skipped (real graph)."""
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager
        from deriva.adapters.graph.models import DirectoryNode
        from deriva.services.extraction import _extract_directory_classification

        close_database()
        with GraphManager() as gm:
            gm.add_node(DirectoryNode(name="billing", path="r/billing", repository_name="r"), node_id="dir::r::billing")
            cfg = SimpleNamespace(instruction="I", example="{}", params=json.dumps(params), temperature=None, max_tokens=None, batch_size=50)
            with patch("deriva.services.extraction.classify_directories", return_value={"success": True, "data": {"nodes": [], "edges": []}}) as classify:
                _extract_directory_classification(cfg, SimpleNamespace(name="r"), gm, MagicMock())
        close_database()

        assert classify.call_args.kwargs["repository_name"] == name

    def test_a_non_boolean_skip_repository_name_is_an_error(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager
        from deriva.adapters.graph.models import DirectoryNode
        from deriva.services.extraction import _extract_directory_classification

        close_database()
        with GraphManager() as gm:
            gm.add_node(DirectoryNode(name="billing", path="r/billing", repository_name="r"), node_id="dir::r::billing")
            cfg = SimpleNamespace(instruction="I", example="{}", params=json.dumps({"skip_repository_name": 1}), temperature=None, max_tokens=None, batch_size=50)
            with patch("deriva.services.extraction.classify_directories") as classify:
                result = _extract_directory_classification(cfg, SimpleNamespace(name="r"), gm, MagicMock())
        close_database()

        assert len(result["errors"]) == 1 and "skip_repository_name" in result["errors"][0]
        classify.assert_not_called()

    def test_same_named_directories_reach_the_llm_as_one_entry(self):
        """Copies of a name are grouped before batching, so they are never split over prompts (real graph)."""
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager
        from deriva.adapters.graph.models import DirectoryNode
        from deriva.services.extraction import _extract_directory_classification

        close_database()
        with GraphManager() as gm:
            for path in ("r/a/records", "r/b", "r/c/records"):
                gm.add_node(DirectoryNode(name=path.rsplit("/", 1)[-1], path=path.removeprefix("r/"), repository_name="r"), node_id=f"dir::r::{path}")
            cfg = SimpleNamespace(instruction="I", example="{}", params=None, temperature=None, max_tokens=None, batch_size=2)
            with patch("deriva.services.extraction.classify_directories", return_value={"success": True, "data": {"nodes": [], "edges": []}}) as classify:
                _extract_directory_classification(cfg, SimpleNamespace(name="r"), gm, MagicMock())
        close_database()

        (batch,) = [c.kwargs["directories"] for c in classify.call_args_list]
        assert [(g["name"], g["paths"]) for g in batch] == [("records", ["r/a/records", "r/c/records"]), ("b", ["r/b"])]

    def test_each_directory_name_reports_its_decision(self):
        """Per name entry the nodes it became (None: no concept or technology), for decision stability (real graph)."""
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager
        from deriva.adapters.graph.models import DirectoryNode
        from deriva.services.extraction import _extract_directory_classification

        close_database()
        with GraphManager() as gm:
            for name in ("billing", "misc"):
                gm.add_node(DirectoryNode(name=name, path=f"r/{name}", repository_name="r"), node_id=f"dir::r::{name}")
            answer = {
                "nodes": [{"id": "concept::r::billing", "labels": ["Graph:BusinessConcept"], "properties": {"conceptName": "Billing"}}],
                "edges": [{"source": "dir::r::billing", "target": "concept::r::billing", "relationship_type": "REPRESENTS"}],
            }
            cfg = SimpleNamespace(instruction="I", example="{}", params=None, temperature=None, max_tokens=None, batch_size=50)
            with patch("deriva.services.extraction.classify_directories", return_value={"success": True, "data": answer}):
                result = _extract_directory_classification(cfg, SimpleNamespace(name="r"), gm, MagicMock())
        close_database()

        assert result["stats"]["decisions"] == {"billing": ["concept::r::billing"], "misc": None}

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
        mock_cfg.params = None
        mock_cfg.temperature = None
        mock_cfg.max_tokens = None
        mock_cfg.batch_size = 50

        mock_repo = MagicMock()
        mock_repo.name = "test_repo"

        graph_manager = MagicMock()
        graph_manager.get_node.return_value = None  # no stored concept yet
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

    def test_passes_the_step_params(self):
        """samples/min_votes on the row reach the classification (majority voting)."""
        from deriva.services.extraction import _extract_directory_classification

        mock_cfg = MagicMock()
        mock_cfg.instruction = "Classify directories"
        mock_cfg.example = "{}"
        mock_cfg.params = '{"samples": 3, "min_votes": 2}'
        mock_cfg.temperature = None
        mock_cfg.max_tokens = None
        mock_cfg.batch_size = 50
        mock_repo = MagicMock()
        mock_repo.name = "test_repo"
        graph_manager = MagicMock()
        graph_manager.query.return_value = [{"name": "src", "path": "src", "id": "dir_1"}]

        with patch("deriva.services.extraction.classify_directories") as mock_classify:
            mock_classify.return_value = {"success": True, "data": {"nodes": [], "edges": []}}
            _extract_directory_classification(mock_cfg, mock_repo, graph_manager, MagicMock())

        assert mock_classify.call_args.kwargs["config"]["params"] == {"samples": 3, "min_votes": 2}


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
            mock_cfg.params = None
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
            mock_cfg.params = None
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


class TestMethodLanguages:
    """With node sources the Method step parses the source files of the languages in params.languages (Python when absent)."""

    FILES = {"app/main.py": "def handle():\n    pass\n", "app/Orders.java": "class Orders {\n  public void place() {}\n}\n"}

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def _extract(self, graph, params):
        from deriva.adapters.graph.models import FileNode, TypeDefinitionNode

        subtypes = {".py": "python", ".java": "java"}
        with tempfile.TemporaryDirectory() as tmpdir:
            for path, text in self.FILES.items():
                (Path(tmpdir) / path).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmpdir) / path).write_text(text, encoding="utf-8")
                file = FileNode(name=Path(path).name, path=path, repository_name="r", file_type="source", subtype=subtypes[Path(path).suffix])
                graph.add_node(file, node_id=f"file::r::{path.replace('/', '_')}")
            # The TypeDefinition step runs first and creates the class that holds the Java method
            orders = TypeDefinitionNode(name="Orders", type_category="class", file_path="app/Orders.java", repository_name="r")
            graph.add_node(orders, node_id="typedef::r::app_Orders.java::Orders")
            cfg = SimpleNamespace(
                node_type="Method",
                input_sources=json.dumps({"files": [], "nodes": [{"label": "TypeDefinition", "property": "codeSnippet"}]}),
                params=json.dumps(params) if params is not None else None,
                instruction="",
                example="",
                temperature=None,
                max_tokens=None,
            )
            return _extract_llm_based(
                node_type="Method",
                cfg=cfg,
                repo=SimpleNamespace(name="r"),
                repo_path=Path(tmpdir),
                classified_files=[{"path": p, "file_type": "source", "subtype": subtypes[Path(p).suffix]} for p in self.FILES],
                graph_manager=graph,
                llm_query_fn=MagicMock(),
                engine=MagicMock(),
            )

    @staticmethod
    def _methods(graph) -> list[str]:
        return sorted(row["name"] for row in graph.query("MATCH (m:Graph:Method) RETURN m.methodName AS name"))

    def test_without_params_only_python_is_parsed(self, graph):
        self._extract(graph, None)

        assert self._methods(graph) == ["handle"]

    def test_the_configured_languages_are_parsed(self, graph):
        result = self._extract(graph, {"languages": ["python", "java"]})

        assert result["errors"] == []
        assert self._methods(graph) == ["handle", "place"]

    @pytest.mark.parametrize("languages", [["pascal"], "java", []])
    def test_unknown_or_malformed_languages_are_an_error(self, graph, languages):
        result = self._extract(graph, {"languages": languages})

        assert len(result["errors"]) == 1 and "languages" in result["errors"][0]
        assert self._methods(graph) == []


class TestInheritanceResolution:
    """An inheritance edge points at the repository's own base type, wherever the type is defined."""

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    @staticmethod
    def _extract(graph, files: dict[str, str]) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            for path, text in files.items():
                (Path(tmpdir) / path).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmpdir) / path).write_text(text, encoding="utf-8")
            cfg = SimpleNamespace(
                node_type="TypeDefinition",
                input_sources=json.dumps({"files": [{"type": "source", "subtype": "java"}]}),
                params=None,
                instruction="",
                example="",
                temperature=None,
                max_tokens=None,
            )
            return _extract_llm_based(
                node_type="TypeDefinition",
                cfg=cfg,
                repo=SimpleNamespace(name="r"),
                repo_path=Path(tmpdir),
                classified_files=[{"path": path, "file_type": "source", "subtype": "java"} for path in files],
                graph_manager=graph,
                llm_query_fn=MagicMock(),
                engine=MagicMock(),
            )

    @staticmethod
    def _inherits(graph) -> list[tuple[str, str, str]]:
        rows = graph.query(
            "MATCH (a:Graph:TypeDefinition)-[e]->(b:Graph:TypeDefinition) WHERE type(e) = 'Graph:INHERITS' "
            "RETURN a.typeName AS source, b.typeName AS target, b.category AS category"
        )
        return sorted((row["source"], row["target"], row["category"]) for row in rows)

    @staticmethod
    def _placeholders(graph) -> list[str]:
        rows = graph.query("MATCH (t:Graph:TypeDefinition) WHERE t.category = 'external_reference' RETURN t.typeName AS name")
        return sorted(row["name"] for row in rows)

    def test_a_base_type_defined_in_another_file_is_the_target(self, graph):
        self._extract(graph, {"shapes/Shape.java": "public interface Shape {}\n", "shapes/Circle.java": "public class Circle implements Shape {}\n"})

        (edge,) = self._inherits(graph)
        assert edge[:2] == ("Circle", "Shape")
        assert edge[2] != "external_reference"
        assert self._placeholders(graph) == []

    def test_type_arguments_are_not_part_of_the_base_name(self, graph):
        self._extract(graph, {"Renderer.java": "public abstract class Renderer<T> {}\n", "Circle.java": "public class Circle extends Renderer<String> {}\n"})

        assert [edge[:2] for edge in self._inherits(graph)] == [("Circle", "Renderer")]
        assert self._placeholders(graph) == []

    def test_an_external_base_type_keeps_a_placeholder(self, graph):
        self._extract(graph, {"Circle.java": "public class Circle implements Serializable {}\n"})

        assert self._inherits(graph) == [("Circle", "Serializable", "external_reference")]

    def test_a_name_defined_twice_keeps_a_placeholder(self, graph):
        self._extract(
            graph,
            {
                "a/Shape.java": "public interface Shape {}\n",
                "b/Shape.java": "public interface Shape {}\n",
                "c/Circle.java": "public class Circle implements Shape {}\n",
            },
        )

        assert self._inherits(graph) == [("Circle", "Shape", "external_reference")]


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


class TestRepositoryWalkExclusions:
    """The repository walk and the extraction fingerprint follow the excluded_directories setting."""

    def test_list_repo_files_skips_excluded_directories(self, tmp_path):
        from deriva.services.extraction import list_repo_files

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("x")
        (tmp_path / "src" / "app.pyc").write_text("x")
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        (tmp_path / "node_modules" / "pkg" / "index.js").write_text("x")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x")

        assert list_repo_files(tmp_path, [".git", "node_modules"]) == ["src/app.py"]

    def test_fingerprint_changes_with_excluded_directories(self):
        from deriva.services import extraction

        versions = {"extraction": {"File": 1}}
        with (
            patch.object(extraction, "RepoManager") as repo_mgr,
            patch.object(extraction.config, "get_excluded_directories", side_effect=[[".git"], [".git", "node_modules"]]),
        ):
            repo_mgr.return_value.get_repository_info.return_value = MagicMock(last_commit="abc")
            first = extraction.compute_extraction_fingerprint(MagicMock(), "repo", versions)
            second = extraction.compute_extraction_fingerprint(MagicMock(), "repo", versions)

        assert first != second

    def test_the_storage_format_is_part_of_the_fingerprint(self):
        """Graphs written in an older storage layout are extracted again, never read as cached."""
        from deriva.services import extraction

        versions = {"extraction": {"File": 1}}
        with (
            patch.object(extraction, "RepoManager") as repo_mgr,
            patch.object(extraction.config, "get_excluded_directories", return_value=[".git"]),
        ):
            repo_mgr.return_value.get_repository_info.return_value = MagicMock(last_commit="abc")
            first = extraction.compute_extraction_fingerprint(MagicMock(), "repo", versions)
            with patch.object(extraction, "STORAGE_FORMAT", 99):
                second = extraction.compute_extraction_fingerprint(MagicMock(), "repo", versions)

        assert first != second


class TestConceptNodesMergeAcrossFiles:
    """Every BusinessConcept write merges with the stored node, so file order does not matter."""

    @staticmethod
    def _store(order):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager
        from deriva.adapters.graph.models import BusinessConceptNode
        from deriva.services.extraction import _add_concept_node

        occurrences = {
            "readme": BusinessConceptNode("User", "entity", "from readme", "repo/README.md", "repo", 0.9),
            "rtf": BusinessConceptNode("User", "actor", "from requirements", "repo/docs/requirements.rtf", "repo", 0.9),
        }
        close_database()
        gm = GraphManager()
        gm.connect()
        try:
            for key in order:
                _add_concept_node(gm, occurrences[key], "concept::repo::user")
            return gm.get_node("concept::repo::user")["properties"], gm.query("MATCH (n:Graph:BusinessConcept) WHERE 'actor' IN n.conceptTypes RETURN n.id AS id")
        finally:
            gm.disconnect()
            close_database()

    def test_same_node_for_either_file_order(self):
        first, _ = self._store(["readme", "rtf"])
        second, _ = self._store(["rtf", "readme"])

        drop = {"extracted_at", "created_at", "updated_at"}
        assert {k: v for k, v in first.items() if k not in drop} == {k: v for k, v in second.items() if k not in drop}
        assert first["conceptTypes"] == ["actor", "entity"]

    def test_actor_query_finds_the_concept(self):
        _, rows = self._store(["rtf", "readme"])

        assert rows == [{"id": "concept::repo::user"}]


class TestExtractionMethodFilter:
    """``extraction_methods`` selects steps; a filtered run is not a full extraction."""

    @staticmethod
    def _cfg(node_type, method):
        cfg = MagicMock()
        cfg.node_type = node_type
        cfg.input_sources = None
        cfg.extraction_method = method
        return cfg

    def _run(self, tmpdir, extraction_methods, progress=None):
        graph_manager = MagicMock()
        repo = MagicMock()
        repo.name = "test_repo"
        repo.path = tmpdir
        configs = [self._cfg("Repository", "structural"), self._cfg("BusinessConcept", "llm")]
        with (
            patch("deriva.services.extraction.RepoManager") as repo_mgr,
            patch("deriva.services.extraction.config.get_extraction_configs", return_value=configs),
            patch("deriva.services.extraction.config.get_file_types", return_value=[]),
            patch("deriva.services.extraction.compute_extraction_fingerprint", return_value="fp"),
        ):
            repo_mgr.return_value.list_repositories.return_value = [repo]
            result = run_extraction(MagicMock(), graph_manager, extraction_methods=extraction_methods, progress=progress)
        return result, graph_manager

    def test_empty_selection_runs_no_steps(self, tmp_path):
        result, graph_manager = self._run(str(tmp_path), [])

        assert result["stats"]["steps_skipped"] == 2
        graph_manager.add_node.assert_not_called()

    def test_warns_when_no_step_matches(self, tmp_path):
        """A method filter that selects nothing is reported, not a silent success."""
        result, _ = self._run(str(tmp_path), ["ast"])

        assert any("No enabled extraction step" in w and "ast" in w for w in result["warnings"])

    def test_filtered_run_does_not_write_the_fingerprint(self, tmp_path):
        _, graph_manager = self._run(str(tmp_path), ["structural"])

        graph_manager.set_extraction_fingerprint.assert_not_called()

    def test_full_run_writes_the_fingerprint(self, tmp_path):
        _, graph_manager = self._run(str(tmp_path), None)

        graph_manager.set_extraction_fingerprint.assert_called_once_with("test_repo", "fp")

    def test_progress_total_counts_only_selected_steps(self, tmp_path):
        progress = MagicMock()
        self._run(str(tmp_path), ["structural"], progress=progress)

        progress.start_phase.assert_called_once_with("extraction", 1)


class TestExtractionStepFilter:
    """``steps`` runs only the named steps, in their sequence order (the step benchmark repeats one step)."""

    @staticmethod
    def _cfg(node_type):
        return SimpleNamespace(node_type=node_type, input_sources=None, extraction_method="structural")

    def _run(self, tmpdir, steps):
        graph_manager = MagicMock()
        repo = SimpleNamespace(name="test_repo", path=tmpdir)
        configs = [self._cfg("Repository"), self._cfg("Directory"), self._cfg("File")]
        with (
            patch("deriva.services.extraction.RepoManager") as repo_mgr,
            patch("deriva.services.extraction.config.get_extraction_configs", return_value=configs),
            patch("deriva.services.extraction.config.get_file_types", return_value=[]),
            patch("deriva.services.extraction.compute_extraction_fingerprint", return_value="fp"),
            patch("deriva.services.extraction._run_extraction_step", return_value={}) as run_step,
        ):
            repo_mgr.return_value.list_repositories.return_value = [repo]
            result = run_extraction(MagicMock(), graph_manager, steps=steps)
        return result, graph_manager, [c.kwargs["cfg"].node_type for c in run_step.call_args_list]

    def test_only_the_named_steps_run_in_sequence_order(self, tmp_path):
        _, _, ran = self._run(str(tmp_path), ["File", "Repository"])

        assert ran == ["Repository", "File"]

    def test_unknown_step_is_an_error(self, tmp_path):
        result, _, ran = self._run(str(tmp_path), ["Nope"])

        assert not result["success"]
        assert any("Nope" in e for e in result["errors"])
        assert ran == []

    def test_filtered_run_does_not_write_the_fingerprint(self, tmp_path):
        _, graph_manager, _ = self._run(str(tmp_path), ["Repository"])

        graph_manager.set_extraction_fingerprint.assert_not_called()


class TestLLMExtractionLabels:
    """Node types an LLM-only re-extraction clears are the ones its LLM steps create."""

    def test_returns_enabled_llm_step_node_types(self):
        from deriva.services.extraction import llm_extraction_labels

        configs = [
            TestExtractionMethodFilter._cfg("Repository", "structural"),
            TestExtractionMethodFilter._cfg("BusinessConcept", "llm"),
            TestExtractionMethodFilter._cfg("ExternalDependency", "parser"),
            TestExtractionMethodFilter._cfg("Technology", "llm"),
        ]
        with patch("deriva.services.extraction.config.get_extraction_configs", return_value=configs) as get:
            labels = llm_extraction_labels(MagicMock())

        assert labels == ["BusinessConcept", "Technology"]
        assert get.call_args.kwargs["enabled_only"] is True


def test_concept_node_keeps_the_voted_types():
    """The types a concept got by majority vote survive into the graph node."""
    from deriva.services.extraction import _create_node_from_data

    node = _create_node_from_data(
        "BusinessConcept",
        {"properties": {"conceptName": "User", "conceptType": "entity", "conceptTypes": ["actor", "entity"], "description": "d", "originSource": "a.md"}},
        "repo",
    )

    assert node.to_dict()["conceptTypes"] == ["actor", "entity"]


def test_the_nodes_and_edges_a_step_writes_reach_the_run_log(tmp_path):
    """The run log names every node and edge a step wrote (GraphNode and Edge objects of a benchmark's event log), each once."""
    from contextlib import contextmanager

    from deriva.adapters.graph.manager import GraphWrites

    run_logger = MagicMock()
    step_ctx = MagicMock()
    run_logger.step_start.return_value = step_ctx
    repo = SimpleNamespace(name="test_repo", path=str(tmp_path), url="u", branch="main")
    graph_manager = MagicMock()
    written = GraphWrites()

    @contextmanager
    def recording():
        yield written

    graph_manager.recording = recording

    def step(**kwargs):
        # A step may write a node twice (merge); the step function reports only some of its edges
        written.nodes.extend(["dir::test_repo::a", "dir::test_repo::b", "dir::test_repo::a"])
        written.edges.extend(["CONTAINS_dir::test_repo::a_dir::test_repo::b", "IMPORTS_dir::test_repo::b_dir::test_repo::a"])
        return {"nodes_created": 2, "edges_created": 2, "edge_ids": ["CONTAINS_dir::test_repo::a_dir::test_repo::b"], "errors": []}

    with (
        patch("deriva.services.extraction.RepoManager") as repo_mgr,
        patch("deriva.services.extraction.config.get_extraction_configs", return_value=[SimpleNamespace(node_type="Directory", extraction_method="structural")]),
        patch("deriva.services.extraction.config.get_file_types", return_value=[]),
        patch("deriva.services.extraction._run_extraction_step", side_effect=step),
    ):
        repo_mgr.return_value.list_repositories.return_value = [repo]
        run_extraction(MagicMock(), graph_manager, run_logger=run_logger)

    assert [c.args[0] for c in step_ctx.add_object.call_args_list] == ["dir::test_repo::a", "dir::test_repo::b"]
    assert [c.args[0] for c in step_ctx.add_edge.call_args_list] == ["CONTAINS_dir::test_repo::a_dir::test_repo::b", "IMPORTS_dir::test_repo::b_dir::test_repo::a"]


class TestDeployableUnitStep:
    """The DeployableUnit step writes one node per unit with INCLUDES edges to its member files, and replaces what it wrote before."""

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def _run(self, graph, tmpdir, files, params=None, repo="r"):
        from deriva.adapters.graph.models import FileNode

        for path, (file_type, subtype, text) in files.items():
            (Path(tmpdir) / path).parent.mkdir(parents=True, exist_ok=True)
            (Path(tmpdir) / path).write_text(text, encoding="utf-8")
            node = FileNode(name=Path(path).name, path=path, repository_name=repo, file_type=file_type, subtype=subtype)
            graph.add_node(node, node_id=f"file::{repo}::{path.replace('/', '_')}")
        cfg = SimpleNamespace(
            node_type="DeployableUnit",
            params=json.dumps(params or {"code_subtypes": ["java", "python"]}),
            input_sources="",
            instruction="",
            example="",
            temperature=None,
            max_tokens=None,
            batch_size=1,
        )
        return _run_extraction_step(cfg, SimpleNamespace(name=repo), Path(tmpdir), [], [], graph, None, MagicMock())

    def test_each_repository_of_a_combined_graph_keeps_its_own_units(self, graph):
        """A combined graph runs the step once per repository: a pass reads and replaces only its repository's units."""
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            self._run(graph, first, {"shop/Dockerfile": ("config", None, "FROM base\n"), "shop/Shop.java": ("source", "java", "class Shop {}\n")}, repo="a")
            self._run(graph, second, {"desk/Dockerfile": ("config", None, "FROM base\n"), "desk/Desk.java": ("source", "java", "class Desk {}\n")}, repo="b")

        units = graph.query("MATCH (u:Graph:DeployableUnit) RETURN u.id AS id, u.repository_name AS repo ORDER BY id")
        assert [(u["id"], u["repo"]) for u in units] == [("unit::a::shop", "a"), ("unit::b::desk", "b")]
        members = graph.query("MATCH (u:Graph:DeployableUnit)-[:`Graph:INCLUDES`]->(f:Graph:File) RETURN u.id AS unit, f.filePath AS path ORDER BY unit, path")
        assert [(m["unit"], m["path"]) for m in members] == [
            ("unit::a::shop", "a/shop/Dockerfile"),
            ("unit::a::shop", "a/shop/Shop.java"),
            ("unit::b::desk", "b/desk/Desk.java"),
            ("unit::b::desk", "b/desk/Dockerfile"),
        ]

    def test_the_member_count_counts_the_pages_too(self, graph):
        files = {
            "pyproject.toml": ("config", None, '[project]\nname = "shop"\n[project.scripts]\nshop = "app.main:run"\n'),
            "app/main.py": ("source", "python", "def run(): pass\n"),
            "app/templates/home.html": ("config", None, "<html></html>\n"),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            self._run(graph, tmpdir, files)

        (unit,) = graph.query("MATCH (u:Graph:DeployableUnit) RETURN u.memberCount AS count")
        assert unit["count"] == 2

    def test_naming_must_be_an_object(self, graph):
        with tempfile.TemporaryDirectory() as tmpdir, pytest.raises(ValueError, match="naming"):
            self._run(graph, tmpdir, {}, params={"code_subtypes": ["java"], "naming": ["Server"]})

    def test_units_and_their_members_are_written(self, graph):
        files = {
            "shop/Dockerfile": ("config", None, "FROM base\n"),
            "shop/src/Shop.java": ("source", "java", "class Shop {}\n"),
            "proxy/Dockerfile": ("config", None, "FROM nginx\n"),
            "README.md": ("docs", None, "- shop: the storefront\n"),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run(graph, tmpdir, files)

        assert result["errors"] == [] and result["nodes_created"] == 1
        units = graph.query("MATCH (u:Graph:DeployableUnit) RETURN u.id AS id, u.name AS name, u.unitKind AS kind, u.readmeLines AS readme")
        assert [(u["id"], u["name"], u["kind"], list(u["readme"])) for u in units] == [("unit::r::shop", "shop", "container", ["shop: the storefront"])]
        members = graph.query("MATCH (u:Graph:DeployableUnit)-[:`Graph:INCLUDES`]->(f:Graph:File) RETURN f.filePath AS path ORDER BY path")
        assert [m["path"] for m in members] == ["r/shop/Dockerfile", "r/shop/src/Shop.java"]

    def test_a_second_run_replaces_the_units_of_the_first(self, graph):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._run(graph, tmpdir, {"shop/Dockerfile": ("config", None, "FROM base\n"), "shop/Shop.java": ("source", "java", "class Shop {}\n")})
            graph.delete_node("file::r::shop_Dockerfile")
            self._run(graph, tmpdir, {})

        # Without the Dockerfile there is no container unit: the repository is the unit
        assert [u["id"] for u in graph.query("MATCH (u:Graph:DeployableUnit) RETURN u.id AS id")] == ["unit::r::r"]

    def test_web_entries_and_the_readme_title_are_written_on_the_unit(self, graph):
        files = {
            "pyproject.toml": ("config", None, '[project]\nname = "shop"\n[project.scripts]\nshop = "app.main:run"\n'),
            "app/main.py": ("source", "python", "def run(): pass\n"),
            "app/templates/home.html": ("config", None, "<html></html>\n"),
            "README.md": ("docs", None, "# Shop Platform\n"),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            self._run(graph, tmpdir, files)

        (unit,) = graph.query("MATCH (u:Graph:DeployableUnit) RETURN u.id AS id, u.webEntries AS web, u.readmeTitle AS title")
        assert list(unit["web"]) == ["r/app/templates/home.html"] and unit["title"] == "Shop Platform"
        # A script unit's members are its import closure; its pages hang below it too
        members = graph.query("MATCH (u:Graph:DeployableUnit)-[:`Graph:INCLUDES`]->(f:Graph:File) RETURN f.filePath AS path ORDER BY path")
        assert [m["path"] for m in members] == ["r/app/main.py", "r/app/templates/home.html"]

    def test_the_web_signals_come_from_the_params(self, graph):
        files = {"shop/Dockerfile": ("config", None, "FROM base\n"), "shop/Shop.java": ("source", "java", "class Shop {}\n"), "shop/web/start.page": ("config", None, "x\n")}
        with tempfile.TemporaryDirectory() as tmpdir:
            self._run(graph, tmpdir, files, params={"code_subtypes": ["java"], "web_ui": {"files": ["*.page"]}})

        (unit,) = graph.query("MATCH (u:Graph:DeployableUnit) RETURN u.webEntries AS web")
        assert list(unit["web"]) == ["r/shop/web/start.page"]
        with tempfile.TemporaryDirectory() as tmpdir, pytest.raises(ValueError, match="web_ui"):
            self._run(graph, tmpdir, {}, params={"code_subtypes": ["java"], "web_ui": {"files": "*.page"}})

    def test_name_candidates_are_written_and_skip_the_technologies_in_the_graph(self, graph):
        from deriva.adapters.graph.models import TechnologyNode

        graph.add_node(TechnologyNode(name="Shop Admin", tech_category="service", repository_name="r"), node_id="tech::r::shopadmin")
        files = {
            "README.md": ("docs", None, "# Shop - Tea Store\n\n| Part | Runtime |\n|---|---|\n| Order Desk | Java |\n"),
            "desk/Dockerfile": ("config", None, "FROM base\n"),
            "desk/Desk.java": ("source", "java", "class Desk {}\n"),
            "shop-admin/Dockerfile": ("config", None, "FROM base\n"),
            "shop-admin/Admin.java": ("source", "java", "class Admin {}\n"),
        }
        params = {
            "code_subtypes": ["java"],
            "naming": {"generic_words": ["Server", "Application"], "title_cut_words": ["with"], "kind_nouns": {"container": "Server", "*": "Application"}},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            self._run(graph, tmpdir, files, params=params)

        units = {u["id"]: u for u in graph.query("MATCH (u:Graph:DeployableUnit) RETURN u.id AS id, u.product AS product, u.nameCandidates AS names, u.nameSources AS sources")}
        assert units["unit::r::desk"]["product"] == "Shop"
        assert list(units["unit::r::desk"]["names"]) == ["Order Desk", "Desk"] and list(units["unit::r::desk"]["sources"]) == ["docs", "structure"]
        assert list(units["unit::r::shop-admin"]["names"]) == ["Shop Admin Server"]  # the technology's name is taken
        with tempfile.TemporaryDirectory() as tmpdir, pytest.raises(ValueError, match="naming"):
            self._run(graph, tmpdir, {}, params={"code_subtypes": ["java"], "naming": {"generic_words": "Server"}})

    def test_the_rules_need_code_subtypes(self, graph):
        with tempfile.TemporaryDirectory() as tmpdir, pytest.raises(ValueError, match="code_subtypes"):
            self._run(graph, tmpdir, {}, params={"container_files": ["Dockerfile"]})


class TestDataEntityStep:
    """The DataEntity step writes one node per persistent concept with INCLUDES edges to its types, and replaces what it wrote before."""

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def _cfg(self, params):
        return SimpleNamespace(node_type="DataEntity", params=json.dumps(params), input_sources="", instruction="", example="", temperature=None, max_tokens=None, batch_size=1)

    def _add_type(self, graph, name, path, decorators=(), bases=()):
        from deriva.adapters.graph.models import TypeDefinitionNode

        node_id = f"typedef::r::{path}::{name}"
        graph.add_node(TypeDefinitionNode(name=name, type_category="class", file_path=path, repository_name="r", decorators=list(decorators)), node_id=node_id)
        for base in bases:
            graph.add_edge(node_id, f"typedef::r::{base}", "INHERITS")
        return node_id

    def test_entities_are_written_with_their_types_and_the_rest_is_reported(self, graph):
        from deriva.adapters.graph.models import TypeDefinitionNode

        graph.add_node(TypeDefinitionNode(name="RootEntity", type_category="interface", file_path="lib/RootEntity.java", repository_name="r"), node_id="typedef::r::RootEntity")
        a = self._add_type(graph, "PolicyAggregateRoot", "policy/Policy.java", decorators=["Entity"], bases=["RootEntity"])
        b = self._add_type(graph, "PolicyAggregateRoot", "quotes/Policy.java", decorators=["Entity"], bases=["RootEntity"])
        self._add_type(graph, "PolicyItem", "policy/Item.java", decorators=["Entity"])
        params = {"root_markers": ["RootEntity"], "entity_annotations": ["Entity"], "name_suffixes": ["AggregateRoot"]}

        result = _run_extraction_step(self._cfg(params), SimpleNamespace(name="r"), Path("."), [], [], graph, None, MagicMock())

        assert result["errors"] == [] and result["nodes_created"] == 1
        (entity,) = graph.query("MATCH (d:Graph:DataEntity) RETURN d.id AS id, d.name AS name, d.signal AS signal, d.nameCandidates AS names")
        assert (entity["id"], entity["name"], entity["signal"], list(entity["names"])) == ("entity::r::policy", "Policy", "aggregate root", ["Policy"])
        types = graph.query("MATCH (d:Graph:DataEntity)-[:`Graph:INCLUDES`]->(t:Graph:TypeDefinition) RETURN t.id AS id ORDER BY id")
        assert [t["id"] for t in types] == sorted([a, b])
        assert result["excluded"] == [{"type": "PolicyItem", "reason": "part of an aggregate"}]

        self._run_again = _run_extraction_step(self._cfg({**params, "root_markers": []}), SimpleNamespace(name="r"), Path("."), [], [], graph, None, MagicMock())
        names = sorted(r["name"] for r in graph.query("MATCH (d:Graph:DataEntity) RETURN d.name AS name"))
        assert names == ["Policy", "Policy Item"]  # without roots both are ORM entities; the old nodes are gone

    def test_only_the_repositories_own_types_count_and_its_entities_carry_the_repository(self, graph):
        from deriva.adapters.graph.models import TypeDefinitionNode

        graph.add_node(TypeDefinitionNode(name="Order", type_category="class", file_path="Order.java", repository_name="r", decorators=["Entity"]), node_id="typedef::r::Order")
        graph.add_node(
            TypeDefinitionNode(name="Invoice", type_category="class", file_path="Invoice.java", repository_name="other", decorators=["Entity"]), node_id="typedef::other::Invoice"
        )

        _run_extraction_step(self._cfg({"entity_annotations": ["Entity"]}), SimpleNamespace(name="r"), Path("."), [], [], graph, None, MagicMock())

        rows = graph.query("MATCH (d:Graph:DataEntity) RETURN d.name AS name, d.repository_name AS repo")
        assert [(r["name"], r["repo"]) for r in rows] == [("Order", "r")]

    def test_a_table_is_linked_to_the_code_files_that_name_it(self, graph, tmp_path):
        from deriva.adapters.graph.models import FileNode, TypeDefinitionNode
        from deriva.modules.derivation.base import unit_scopes

        (tmp_path / "db").mkdir()
        (tmp_path / "app").mkdir()
        (tmp_path / "db/schema.sql").write_text("CREATE TABLE benchmark_runs (id INT);", encoding="utf-8")
        (tmp_path / "app/store.py").write_text('q = "SELECT * FROM benchmark_runs"', encoding="utf-8")
        (tmp_path / "app/util.py").write_text("x = 1", encoding="utf-8")
        for path, subtype in (("db/schema.sql", "sql"), ("app/store.py", "python"), ("app/util.py", "python")):
            graph.add_node(FileNode(name=path.rsplit("/", 1)[-1], path=path, repository_name="r", file_type="source", subtype=subtype), node_id=f"file::r::{path}")
        graph.add_node(TypeDefinitionNode(name="benchmark_runs", type_category="table", file_path="db/schema.sql", repository_name="r"), node_id="typedef::r::benchmark_runs")

        _run_extraction_step(self._cfg({"table_mentions": True}), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())

        named = graph.query("MATCH (d:Graph:DataEntity)-[:`Graph:NAMED_IN`]->(f:Graph:File) RETURN d.name AS entity, f.filePath AS path")
        assert [(r["entity"], r["path"]) for r in named] == [("Benchmark Run", "r/app/store.py")]
        assert "r/app/store.py" in unit_scopes(graph).entity_files["entity::r::benchmarkrun"]

    def test_the_signals_are_validated(self, graph):
        with pytest.raises(ValueError, match="DataEntity"):
            _run_extraction_step(self._cfg({"technical_words": "log"}), SimpleNamespace(name="r"), Path("."), [], [], graph, None, MagicMock())


class TestRerunnableSteps:
    """A step run removes what it wrote before and no longer produces; running it twice leaves the graph as it was."""

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def _types(self, graph, entities):
        from deriva.adapters.graph.models import TypeDefinitionNode

        for name in entities:
            graph.add_node(
                TypeDefinitionNode(name=name, type_category="class", file_path=f"{name}.java", repository_name="r", decorators=["Entity"]), node_id=f"typedef::r::{name}"
            )

    def _run(self, graph):
        cfg = SimpleNamespace(
            node_type="DataEntity",
            params=json.dumps({"entity_annotations": ["Entity"]}),
            input_sources="",
            instruction="",
            example="",
            temperature=None,
            max_tokens=None,
            batch_size=1,
        )
        return _run_extraction_step(cfg, SimpleNamespace(name="r"), Path("."), [], [], graph, None, MagicMock())

    @staticmethod
    def _snapshot(graph):
        nodes = sorted((r["id"], sorted(r["p"].items())) for r in graph.query("MATCH (n) WHERE n.id IS NOT NULL RETURN n.id AS id, properties(n) AS p"))
        edges = sorted(
            (r["a"], r["t"], r["b"], sorted((r["p"] or {}).items())) for r in graph.query("MATCH (a)-[r]->(b) RETURN a.id AS a, type(r) AS t, b.id AS b, properties(r) AS p")
        )
        return nodes, edges

    def test_running_a_step_twice_leaves_the_graph_as_it_was(self, graph):
        self._types(graph, ["Order", "Invoice"])
        self._run(graph)
        first = self._snapshot(graph)

        self._run(graph)

        assert self._snapshot(graph) == first

    def test_an_entity_no_longer_produced_goes_and_one_produced_again_keeps_other_edges(self, graph):
        self._types(graph, ["Order", "Invoice"])
        self._run(graph)
        graph.add_edge("typedef::r::Order", "entity::r::order", "REFERENCES")  # written by someone else
        graph.delete_node("typedef::r::Invoice")

        result = self._run(graph)

        assert sorted(r["id"] for r in graph.query("MATCH (d:Graph:DataEntity) RETURN d.id AS id")) == ["entity::r::order"]
        assert graph.query("MATCH (a {id: 'typedef::r::Order'})-[r]->(b {id: 'entity::r::order'}) RETURN count(r) AS n")[0]["n"] == 1
        assert result["swept"] == {"nodes": 1, "edges": 0}

    def test_a_run_with_errors_sweeps_nothing(self, graph):
        self._types(graph, ["Order"])
        self._run(graph)
        graph.delete_node("typedef::r::Order")

        with patch("deriva.services.extraction._run_step_writes", return_value={"nodes_created": 0, "edges_created": 0, "errors": ["boom"]}):
            result = self._run(graph)

        assert result["swept"] == {"nodes": 0, "edges": 0, "skipped": "errors"}
        assert graph.node_exists("entity::r::order")


class TestTagSteps:
    """graph tag-steps: nodes and edges written before steps were tagged get their owner by rule; the rest is reported."""

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def test_untagged_nodes_and_edges_get_their_step_and_unknown_ones_are_reported(self, graph):
        from deriva.adapters.graph.models import BusinessConceptNode, FileNode, TypeDefinitionNode
        from deriva.services.extraction import tag_steps

        graph.add_node(FileNode(name="a.py", path="a.py", repository_name="r", file_type="source"), node_id="file::r::a")
        graph.add_node(TypeDefinitionNode(name="A", type_category="class", file_path="a.py", repository_name="r"), node_id="typedef::r::a::A")
        graph.add_node(BusinessConceptNode("Billing", "entity", "", "", "r", 0.9, extraction_method="llm-directory"), node_id="concept::r::billing")
        graph.add_edge("file::r::a", "typedef::r::a::A", "CONTAINS")
        graph.add_edge("typedef::r::a::A", "file::r::a", "CONTAINS")  # no rule for this one

        report = tag_steps(graph, "r")

        steps = {r["id"]: list(r["s"]) for r in graph.query("MATCH (n) WHERE n.id IS NOT NULL RETURN n.id AS id, n.extractSteps AS s")}
        assert steps == {"file::r::a": ["File"], "typedef::r::a::A": ["TypeDefinition"], "concept::r::billing": ["DirectoryClassification"]}
        edge = graph.query("MATCH (a {id: 'file::r::a'})-[r]->(b) RETURN r.extractStep AS s")[0]["s"]
        assert edge == "TypeDefinition"
        assert report["nodes"] == {"File": 1, "TypeDefinition": 1, "DirectoryClassification": 1} and report["untagged_nodes"] == {}
        assert report["untagged_edges"] == {"CONTAINS TypeDefinition->File": 1}
        assert tag_steps(graph, "r")["nodes"] == {}  # tagged nodes are left as they are


def test_a_steps_own_node_it_only_links_to_again_is_kept():
    """A placeholder the step made before and now only links to (it exists, so it is not written again) stays."""
    from deriva.adapters.grafeo.manager import close_database
    from deriva.adapters.graph import GraphManager
    from deriva.adapters.graph.models import TypeDefinitionNode
    from deriva.services import extraction as service

    def step(cfg, repo, repo_path, classified, undefined, gm, llm, engine, model=None):
        if not gm.node_exists("typedef::r::Base"):
            gm.add_node(TypeDefinitionNode(name="Base", type_category="class", file_path="external", repository_name="r"), node_id="typedef::r::Base")
        gm.add_node(TypeDefinitionNode(name="A", type_category="class", file_path="a.py", repository_name="r"), node_id="typedef::r::A")
        gm.add_edge("typedef::r::A", "typedef::r::Base", "INHERITS")
        return {"nodes_created": 1, "edges_created": 1, "errors": []}

    close_database()
    with GraphManager() as gm:
        cfg = SimpleNamespace(node_type="TypeDefinition")
        with patch.object(service, "_run_step_writes", side_effect=step):
            service._run_extraction_step(cfg, SimpleNamespace(name="r"), Path("."), [], [], gm, None, MagicMock())
            result = service._run_extraction_step(cfg, SimpleNamespace(name="r"), Path("."), [], [], gm, None, MagicMock())
        assert result["swept"] == {"nodes": 0, "edges": 0}
        assert gm.node_exists("typedef::r::Base")
    close_database()


class TestDeploymentStep:
    """The Deployment step writes the primary environment, its deployed services and the system software (no LLM)."""

    PARAMS = {
        "technologies": [
            {"name": "PostgreSQL", "kind": "database", "aliases": ["postgres", "psycopg2"]},
            {"name": "Java runtime", "kind": "runtime", "aliases": ["eclipse-temurin"]},
            {"name": "CICS", "kind": "transaction monitor", "aliases": ["cics"]},
        ],
        "cloud_resources": {"AWS::ECS::Service": "container"},
        "markers": [{"pattern": r"EXEC\s+CICS", "technology": "cics"}],
        "marker_suffixes": [".cbl"],
        "manifest_runtimes": {"pyproject.toml": "python"},
    }

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def _cfg(self, params):
        return SimpleNamespace(node_type="Deployment", params=json.dumps(params), input_sources="", instruction="", example="", temperature=None, max_tokens=None, batch_size=1)

    def _repo(self, graph, root, files):
        from deriva.adapters.graph.models import DeployableUnitNode, FileNode

        for path, text in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text, encoding="utf-8")
            graph.add_node(FileNode(name=path.rsplit("/", 1)[-1], path=path, repository_name="r", file_type="other", subtype=""), node_id=f"file::r::{path}")
        for name in ("shop", "billing"):
            graph.add_node(DeployableUnitNode(name=name, path=f"r/{name}", unit_kind="container", repository_name="r"), node_id=f"unit::r::{name}")

    def test_the_environment_its_services_and_the_software_are_written(self, graph, tmp_path):
        compose = "services:\n  shop:\n    build: ./shop\n    depends_on: [db]\n  billing:\n    build: ./billing\n  db:\n    image: postgres:15\n"
        self._repo(graph, tmp_path, {"docker-compose.yml": compose, "shop/Dockerfile": "FROM eclipse-temurin:21\n"})

        result = _run_extraction_step(self._cfg(self.PARAMS), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())

        assert result["errors"] == []
        (env,) = graph.query("MATCH (e:Graph:Environment) RETURN e.id AS id, e.name AS name, e.kind AS kind, e.repository_name AS repo")
        assert (env["id"], env["name"], env["kind"], env["repo"]) == ("environment::r::compose", "Docker Compose", "compose", "r")
        deploys = graph.query(
            "MATCH (e:Graph:Environment)-[:`Graph:RUNS`]->(d:Graph:Deployment)-[:`Graph:DEPLOYS`]->(u:Graph:DeployableUnit) RETURN d.name AS d, u.id AS u ORDER BY d"
        )
        assert [(r["d"], r["u"]) for r in deploys] == [("billing", "unit::r::billing"), ("shop", "unit::r::shop")]
        hosted = graph.query("MATCH (e:Graph:Environment)-[:`Graph:HOSTS`]->(s:Graph:Software) RETURN s.name AS s ORDER BY s")
        assert [r["s"] for r in hosted] == ["Java runtime", "PostgreSQL"]
        serves = graph.query("MATCH (s:Graph:Software)-[:`Graph:SERVES`]->(u:Graph:DeployableUnit) RETURN s.name AS s, u.id AS u ORDER BY s")
        assert [(r["s"], r["u"]) for r in serves] == [("Java runtime", "unit::r::shop"), ("PostgreSQL", "unit::r::shop")]
        assert result["software"] == {"listed": 2, "fallback": 0, "unconnected": 0}

    def test_a_cdk_app_is_read_statically_and_is_the_primary_environment(self, graph, tmp_path):
        params = {
            **self.PARAMS,
            "technologies": [*self.PARAMS["technologies"], {"name": "Amazon RDS for PostgreSQL", "kind": "managed service", "aliases": ["aws::rds::dbinstance::postgres"]}],
            "cloud_resources": {"AWS::ECS::Service": "container", "AWS::RDS::DBInstance": "managed"},
            "cloud_qualifiers": {"AWS::RDS::DBInstance": {"property": "Engine"}},
            "cdk_constructs": {
                "aws-ecs.FargateService": {"type": "AWS::ECS::Service", "environment": "AWS ECS Fargate"},
                "aws-rds.DatabaseInstance": {"type": "AWS::RDS::DBInstance"},
            },
        }
        app = (
            "import * as ecs from 'aws-cdk-lib/aws-ecs';\nimport * as rds from 'aws-cdk-lib/aws-rds';\n"
            "const NAMES = ['shop', 'billing'];\n"
            "export class S { constructor(s: any) {\n"
            "  for (const n of NAMES) { new ecs.FargateService(s, `${n}Service`, { serviceName: n }); }\n"
            "  new rds.DatabaseInstance(s, 'Db', { engine: rds.DatabaseInstanceEngine.postgres({}) });\n} }\n"
        )
        compose = "services:\n  shop:\n    build: ./shop\n"
        self._repo(
            graph,
            tmp_path,
            {"docker-compose.yml": compose, "infra/cdk.json": '{"app": "npx ts-node bin/app.ts"}', "infra/lib/stack.ts": app, "shop/x.ts": "new ecs.FargateService(a, 'Nope');"},
        )

        result = _run_extraction_step(self._cfg(params), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())

        assert result["errors"] == []
        (env,) = graph.query("MATCH (e:Graph:Environment) RETURN e.name AS name, e.kind AS kind")
        assert (env["name"], env["kind"]) == ("AWS ECS Fargate", "cloud")
        deploys = graph.query("MATCH (:Graph:Environment)-[:`Graph:RUNS`]->(d:Graph:Deployment)-[:`Graph:DEPLOYS`]->(u) RETURN d.name AS d, u.id AS u ORDER BY d")
        assert [(r["d"], r["u"]) for r in deploys] == [("billingService", "unit::r::billing"), ("shopService", "unit::r::shop")]
        hosted = graph.query("MATCH (e:Graph:Environment)-[:`Graph:HOSTS`]->(s:Graph:Software) RETURN s.name AS s ORDER BY s")
        assert [r["s"] for r in hosted] == ["Amazon RDS for PostgreSQL"]
        # The other environments' services stay on the environment, for Cooperation (names, ports, variables)
        (other,) = graph.query("MATCH (e:Graph:Environment) RETURN e.otherServices AS s")[0]["s"]
        assert json.loads(other) == {"name": "shop", "unit": "unit::r::shop", "environment": {}, "ports": []}

    def test_a_run_with_another_environment_sweeps_the_old_one(self, graph, tmp_path):
        self._repo(graph, tmp_path, {"docker-compose.yml": "services:\n  shop:\n    build: ./shop\n", "shop/a.cbl": "EXEC CICS RETURN"})
        _run_extraction_step(self._cfg(self.PARAMS), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())
        (tmp_path / "docker-compose.yml").unlink()

        _run_extraction_step(self._cfg(self.PARAMS), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())

        assert [r["id"] for r in graph.query("MATCH (e:Graph:Environment) RETURN e.id AS id")] == ["environment::r::mainframe"]
        assert [r["n"] for r in graph.query("MATCH (d:Graph:Deployment) RETURN d.name AS n")] == ["shop"]

    def test_the_signals_are_validated(self, graph, tmp_path):
        with pytest.raises(ValueError, match="Deployment"):
            _run_extraction_step(self._cfg({**self.PARAMS, "markers": [{"pattern": "("}]}), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())


class TestCooperationStep:
    """The Cooperation step writes CONSUMES and SENDS_TO edges between deployable units, from structure (no LLM)."""

    PARAMS = {"send_markers": ["convertAndSend"], "listen_markers": ["@JmsListener"]}

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def _cfg(self, params):
        return SimpleNamespace(node_type="Cooperation", params=json.dumps(params), input_sources="", instruction="", example="", temperature=None, max_tokens=None, batch_size=1)

    def _repo(self, graph, root, files, variables=None):
        from deriva.adapters.graph.models import DeployableUnitNode, DeploymentNode, FileNode

        for name in ("core", "billing"):
            graph.add_node(DeployableUnitNode(name=name, path=f"r/{name}", unit_kind="container", repository_name="r"), node_id=f"unit::r::{name}")
            graph.add_node(
                DeploymentNode(name=name, environment="compose", repository_name="r", variables=(variables or {}).get(name, {}), ports=[]),
                node_id=f"deployment::r::compose::{name}",
            )
            graph.add_edge(f"deployment::r::compose::{name}", f"unit::r::{name}", "DEPLOYS")
        for path, text in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text, encoding="utf-8")
            graph.add_node(FileNode(name=path.rsplit("/", 1)[-1], path=path, repository_name="r", file_type="config", subtype=""), node_id=f"file::r::{path}")
            graph.add_edge(f"unit::r::{path.split('/', 1)[0]}", f"file::r::{path}", "INCLUDES")

    def test_uses_and_message_flows_are_written_with_their_evidence(self, graph, tmp_path):
        files = {
            "core/application.properties": "server.port = 8110\nin.queueName=orders\n",
            "core/Listener.java": '@JmsListener(destination = "${in.queueName}") void on() {}',
            "billing/application.properties": "core.url=http://localhost:8110\nout.queueName=orders\n",
            "billing/Sender.java": '@Value("${out.queueName}") String q; void s() { jms.convertAndSend(q, x); }',
        }
        self._repo(graph, tmp_path, files)

        result = _run_extraction_step(self._cfg(self.PARAMS), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())

        assert result["errors"] == [] and result["links"] == {"endpoint": 1, "messaging": 1}
        rows = graph.query("MATCH (a:Graph:DeployableUnit)-[r]->(b:Graph:DeployableUnit) RETURN a.id AS a, type(r) AS t, b.id AS b, r.channel AS c, r.evidence AS e ORDER BY t")
        assert [(r["a"], r["t"], r["b"], r["c"], r["e"]) for r in rows] == [
            ("unit::r::billing", "Graph:CONSUMES", "unit::r::core", "rest", "endpoint"),
            ("unit::r::billing", "Graph:SENDS_TO", "unit::r::core", "messaging", "messaging"),
        ]

    def test_a_rerun_without_the_evidence_sweeps_the_line(self, graph, tmp_path):
        self._repo(graph, tmp_path, {"core/application.properties": "server.port = 8110\n", "billing/application.properties": "core.url=http://localhost:8110\n"})
        _run_extraction_step(self._cfg(self.PARAMS), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())
        (tmp_path / "billing/application.properties").write_text("nothing=here\n", encoding="utf-8")

        _run_extraction_step(self._cfg(self.PARAMS), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())

        assert graph.query("MATCH (:Graph:DeployableUnit)-[r:`Graph:CONSUMES`]->(:Graph:DeployableUnit) RETURN count(r) AS n")[0]["n"] == 0

    def test_the_services_of_the_other_environments_are_used_too(self, graph, tmp_path):
        """A cloud primary (no ports, no variables) does not hide the compose services that configuration refers to."""
        from deriva.adapters.graph.models import DeployableUnitNode, EnvironmentNode

        for name in ("core", "billing"):
            graph.add_node(DeployableUnitNode(name=name, path=f"r/{name}", unit_kind="container", repository_name="r"), node_id=f"unit::r::{name}")
        compose = [
            {"name": "core", "unit": "unit::r::core", "environment": {}, "ports": [8110]},
            {"name": "billing", "unit": "unit::r::billing", "environment": {"CORE_URL": "http://core:8110"}, "ports": []},
        ]
        graph.add_node(EnvironmentNode(name="AWS ECS Fargate", kind="cloud", repository_name="r", other_services=[json.dumps(s) for s in compose]), node_id="environment::r::cloud")

        result = _run_extraction_step(self._cfg(self.PARAMS), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())

        assert result["errors"] == []
        rows = graph.query("MATCH (a:Graph:DeployableUnit)-[r:`Graph:CONSUMES`]->(b:Graph:DeployableUnit) RETURN a.id AS a, b.id AS b")
        assert [(r["a"], r["b"]) for r in rows] == [("unit::r::billing", "unit::r::core")]

    def test_the_compose_environment_of_a_service_counts_as_its_configuration(self, graph, tmp_path):
        self._repo(graph, tmp_path, {"core/application.properties": "x=1\n"}, variables={"billing": {"CORE_URL": "http://core:8110"}})

        _run_extraction_step(self._cfg(self.PARAMS), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())

        rows = graph.query("MATCH (a)-[r:`Graph:CONSUMES`]->(b) RETURN a.id AS a, b.id AS b")
        assert [(r["a"], r["b"]) for r in rows] == [("unit::r::billing", "unit::r::core")]

    def test_the_signals_are_validated(self, graph, tmp_path):
        with pytest.raises(ValueError, match="Cooperation"):
            _run_extraction_step(self._cfg({"send_markers": "convertAndSend"}), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())


class TestDataDomainStep:
    """The DataDomain step groups the data entities into information domains and writes them with INCLUDES edges (no LLM)."""

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def _cfg(self, params=None):
        return SimpleNamespace(
            node_type="DataDomain",
            params=json.dumps(params or {"identity_words": ["user"]}),
            input_sources="",
            instruction="",
            example="",
            temperature=None,
            max_tokens=None,
            batch_size=1,
        )

    def _type(self, graph, root, name, text):
        from deriva.adapters.graph.models import FileNode, TypeDefinitionNode

        path = f"shop/{name}.java"
        (root / "shop").mkdir(exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
        graph.add_node(FileNode(name=f"{name}.java", path=path, repository_name="r", file_type="source", subtype="java"), node_id=f"file::r::{path}")
        graph.add_node(TypeDefinitionNode(name=name, type_category="class", file_path=path, repository_name="r", decorators=["Entity"]), node_id=f"typedef::r::{name}")

    def _run(self, graph, root, params=None):
        entity_params = json.dumps({"entity_annotations": ["Entity"]})
        entity_cfg = SimpleNamespace(node_type="DataEntity", params=entity_params, input_sources="", instruction="", example="", temperature=None, max_tokens=None, batch_size=1)
        _run_extraction_step(entity_cfg, SimpleNamespace(name="r"), root, [], [], graph, None, MagicMock())  # the entities come first
        with patch("deriva.services.extraction.config.get_extraction_config", return_value=entity_cfg):
            return _run_extraction_step(self._cfg(params), SimpleNamespace(name="r"), root, [], [], graph, None, MagicMock())

    def test_entities_owned_by_one_parent_form_its_domain(self, graph, tmp_path):
        self._type(graph, tmp_path, "Order", '@Entity public class Order { @OneToMany(mappedBy = "order", cascade = {CascadeType.ALL}) private List<OrderLine> lines; }')
        self._type(graph, tmp_path, "OrderLine", "@Entity public class OrderLine { @ManyToOne(optional = false) private Order order; }")
        self._type(graph, tmp_path, "Supplier", "@Entity public class Supplier { }")

        result = self._run(graph, tmp_path)

        assert result["errors"] == [] and result["domains"] == 2
        rows = graph.query("MATCH (d:Graph:DataDomain) RETURN d.id AS id, d.name AS name, d.nameCandidates AS names, d.businessObject AS bo ORDER BY id")
        assert [(r["id"], r["name"], list(r["names"]), r["bo"]) for r in rows] == [
            ("domain::r::order", "Order", ["Order Data"], "Order"),
            ("domain::r::supplier", "Supplier", ["Supplier Data"], "Supplier"),
        ]
        members = graph.query("MATCH (d:Graph:DataDomain {id: 'domain::r::order'})-[:`Graph:INCLUDES`]->(m) RETURN m.id AS id ORDER BY id")
        assert [m["id"] for m in members] == ["entity::r::order", "entity::r::orderline"]

    def test_a_domain_is_used_where_its_members_are(self, graph, tmp_path):
        from deriva.modules.derivation.base import unit_scopes

        self._type(graph, tmp_path, "Order", "@Entity public class Order { @OneToMany(cascade = {CascadeType.ALL}) private List<OrderLine> lines; }")
        self._type(graph, tmp_path, "OrderLine", "@Entity public class OrderLine { }")
        self._run(graph, tmp_path)

        scopes = unit_scopes(graph)

        assert scopes.entity_files["domain::r::order"] == {"r/shop/Order.java", "r/shop/OrderLine.java"}
        assert "domain::r::order" in scopes.entities_of("typedef::r::OrderLine")

    def test_the_signals_are_validated(self, graph, tmp_path):
        with pytest.raises(ValueError, match="DataDomain"):
            self._run(graph, tmp_path, {"identity_words": "user"})


class TestBusinessLayerStep:
    """The BusinessLayer step writes lifecycles (processes), their events and the roles assigned to them (no LLM)."""

    PARAMS = {"markers": [r"require_role\(([^)]*)\)"], "generic_roles": ["admin"], "status_words": ["status"], "min_states": 3}

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def _cfg(self, params):
        return SimpleNamespace(node_type="BusinessLayer", params=json.dumps(params), input_sources="", instruction="", example="", temperature=None, max_tokens=None, batch_size=1)

    def test_a_lifecycle_its_events_and_the_roles_on_it_are_written(self, graph, tmp_path):
        from deriva.adapters.graph.models import DataDomainNode, DataEntityNode, DeployableUnitNode, FileNode, TypeDefinitionNode

        files = {
            "loan/models.py": 'class LoanApplication(Base):\n    status = Column(String(20), default="DRAFT")\n',
            "loan/routes.py": 'require_role("ADMIN", "LOAN_OFFICER")\ndef submit(app):\n    app.status = "SUBMITTED"\n',
            "uw/routes.py": 'require_role("UNDERWRITER")\ndef approve(app):\n    app.status = "APPROVED"\n',
        }
        for path, text in files.items():
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_text(text, encoding="utf-8")
            graph.add_node(FileNode(name=path.rsplit("/", 1)[-1], path=path, repository_name="r", file_type="source", subtype="python"), node_id=f"file::r::{path}")
        for unit in ("loan", "uw"):
            graph.add_node(DeployableUnitNode(name=f"{unit}-service", path=f"r/{unit}", unit_kind="container", repository_name="r"), node_id=f"unit::r::{unit}")
        graph.add_node(TypeDefinitionNode(name="LoanApplication", type_category="class", file_path="loan/models.py", repository_name="r"), node_id="typedef::r::LoanApplication")
        graph.add_node(DataEntityNode(name="Loan Application", signal="orm entity", repository_name="r"), node_id="entity::r::loanapplication")
        graph.add_edge("entity::r::loanapplication", "typedef::r::LoanApplication", "INCLUDES")
        graph.add_node(DataDomainNode(name="Loan Application", kind="single", repository_name="r", business_object="Loan Application"), node_id="domain::r::loanapplication")
        graph.add_edge("domain::r::loanapplication", "entity::r::loanapplication", "INCLUDES")

        result = _run_extraction_step(self._cfg(self.PARAMS), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())

        assert result["errors"] == [] and result["lifecycles"] == 1 and result["roles"] == 2
        (life,) = graph.query("MATCH (l:Graph:Lifecycle) RETURN l.id AS id, l.name AS name, l.states AS states, l.events AS events, l.stateSites AS sites")
        assert "SUBMITTED>r/loan/routes.py" in list(life["sites"]) and "APPROVED>r/uw/routes.py" in list(life["sites"])
        assert (life["name"], list(life["states"]), list(life["events"])) == ("Loan Application Lifecycle", ["DRAFT", "SUBMITTED", "APPROVED"], ["SUBMITTED", "APPROVED"])
        chain = graph.query("MATCH (a)-[:`Graph:TRIGGERS`]->(b:Graph:LifecycleEvent) RETURN a.id AS a, b.name AS b ORDER BY b")
        assert [r["b"] for r in chain] == ["Loan Application Approved", "Loan Application Submitted"]
        assert {r["a"] for r in chain} == {life["id"]}  # no transition in code links the two: both hang off the lifecycle
        roles = graph.query("MATCH (r:Graph:Role)-[:`Graph:ASSIGNED`]->(l:Graph:Lifecycle) RETURN r.name AS r ORDER BY r")
        assert [r["r"] for r in roles] == ["Loan Officer", "Underwriter"]

    def test_the_signals_are_validated(self, graph, tmp_path):
        with pytest.raises(ValueError, match="BusinessLayer"):
            _run_extraction_step(self._cfg({"markers": "require_role"}), SimpleNamespace(name="r"), tmp_path, [], [], graph, None, MagicMock())
