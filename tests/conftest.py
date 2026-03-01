"""
Shared pytest fixtures for Deriva tests.

Fixtures are organized by scope:
- session: Expensive setup done once (e.g., database connections)
- function: Fresh state for each test (default)
"""

import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# =============================================================================
# Sample Data Fixtures
# =============================================================================


@pytest.fixture
def sample_file_paths():
    """Sample file paths for classification tests."""
    return [
        "src/main.py",
        "src/utils/helpers.py",
        "tests/test_main.py",
        "README.md",
        "requirements.txt",
        "config.yaml",
        ".gitignore",
    ]


@pytest.fixture
def sample_file_type_registry():
    """Minimal file type registry for testing."""
    return [
        {"extension": "py", "type": "source", "subtype": "python"},
        {"extension": "md", "type": "documentation", "subtype": "markdown"},
        {"extension": "txt", "type": "documentation", "subtype": "text"},
        {"extension": "yaml", "type": "config", "subtype": "yaml"},
        {"extension": "yml", "type": "config", "subtype": "yaml"},
        {"extension": "json", "type": "config", "subtype": "json"},
    ]


@pytest.fixture
def sample_graph_nodes():
    """Sample graph nodes for validation tests."""
    return [
        {"id": "dir_src", "label": "Directory", "name": "src"},
        {"id": "dir_utils", "label": "Directory", "name": "utils"},
        {"id": "file_main", "label": "File", "name": "main.py"},
        {"id": "type_app", "label": "TypeDefinition", "name": "App"},
    ]


@pytest.fixture
def sample_archimate_elements():
    """Sample ArchiMate elements for validation tests."""
    return [
        {
            "identifier": "app-comp:core",
            "name": "Core Component",
            "element_type": "ApplicationComponent",
            "properties": {"source": "Directory:src", "confidence": 0.85},
        },
        {
            "identifier": "app-comp:utils",
            "name": "Utils Component",
            "element_type": "ApplicationComponent",
            "properties": {"source": "Directory:utils", "confidence": 0.75},
        },
    ]


@pytest.fixture
def sample_relationships():
    """Sample ArchiMate relationships for validation tests."""
    return [
        {
            "identifier": "rel-1",
            "source": "app-comp:core",
            "target": "app-comp:utils",
            "type": "Composition",
        },
    ]


# =============================================================================
# Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_llm_response():
    """Factory fixture for creating mock LLM responses."""

    class MockResponse:
        def __init__(self, content, usage=None, error=None):
            self.content = content
            self.usage = usage or {"prompt_tokens": 100, "completion_tokens": 50}
            self.error = error
            self.response_type = "ResponseType.NEW"

    def _create(content, **kwargs):
        return MockResponse(content, **kwargs)

    return _create


@pytest.fixture
def mock_llm_query_fn(mock_llm_response):
    """Mock LLM query function that returns predefined responses."""

    def _query(prompt, schema):
        # Return a default empty response
        return mock_llm_response('{"elements": []}')

    return _query


# =============================================================================
# TreeSitter Fixtures
# =============================================================================


@pytest.fixture
def treesitter_manager():
    """Provide a TreeSitterManager instance for tests."""
    from deriva.adapters.treesitter import TreeSitterManager

    return TreeSitterManager()


# =============================================================================
# Repository Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_repository(tmp_path):
    """Factory fixture for creating mock repository objects.

    Usage:
        def test_something(mock_repository):
            repo = mock_repository(name="my_repo", files={"src/main.py": "def main(): pass"})
    """
    from unittest.mock import MagicMock

    def _make(name="test_repo", files=None, branch="main"):
        repo = MagicMock()
        repo.name = name
        repo.path = str(tmp_path / name)
        repo.url = f"https://example.com/{name}.git"
        repo.branch = branch

        # Create the repo directory
        repo_dir = tmp_path / name
        repo_dir.mkdir(exist_ok=True)

        # Create any specified files
        if files:
            for file_path, content in files.items():
                full_path = repo_dir / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)

        return repo

    return _make


# =============================================================================
# Session/Pipeline Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_session_dependencies():
    """Mock all PipelineSession external dependencies.

    Usage:
        def test_something(mock_session_dependencies):
            mocks = mock_session_dependencies
            mocks["db"].return_value = ...
    """
    from unittest.mock import patch

    with (
        patch("deriva.services.session.get_connection") as mock_db,
        patch("deriva.services.session.GraphManager") as mock_graph,
        patch("deriva.services.session.ArchimateManager") as mock_archimate,
        patch("deriva.services.session.RepoManager") as mock_repo,
    ):
        yield {
            "db": mock_db,
            "graph": mock_graph,
            "archimate": mock_archimate,
            "repo": mock_repo,
        }


# =============================================================================
# Assertion Helpers (registered as pytest helpers)
# =============================================================================


def assert_success(result, expected=True):
    """Assert operation result success/failure.

    Usage:
        from tests.conftest import assert_success
        assert_success(result)  # Expects success
        assert_success(result, expected=False)  # Expects failure
    """
    assert result["success"] is expected, f"Expected success={expected}, got {result.get('success')}"
    if expected:
        errors = result.get("errors", [])
        assert not errors, f"Unexpected errors: {errors}"


def assert_error_contains(result, message):
    """Assert result failed with specific error message.

    Usage:
        from tests.conftest import assert_error_contains
        assert_error_contains(result, "Missing required")
    """
    assert result["success"] is False, "Expected failure, got success"
    errors = result.get("errors", [])
    assert any(message in err for err in errors), f"Expected '{message}' in errors: {errors}"


# =============================================================================
# Markers
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (no external dependencies)")
    config.addinivalue_line("markers", "integration: Integration tests (require services)")
    config.addinivalue_line("markers", "slow: Slow tests (skipped by default)")
