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
# Markers
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (no external dependencies)")
    config.addinivalue_line("markers", "integration: Integration tests (require services)")
    config.addinivalue_line("markers", "slow: Slow tests (skipped by default)")
