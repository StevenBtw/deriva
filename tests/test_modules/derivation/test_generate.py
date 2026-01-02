"""Tests for modules.derivation.generate module."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest

from deriva.modules.derivation.generate import generate_element


class TestGenerateElement:
    """Tests for generate_element function."""

    def test_empty_graph_results(self):
        """Should return empty result when graph query returns nothing."""
        graph_manager = Mock()
        graph_manager.query.return_value = []
        archimate_manager = Mock()
        llm_query_fn = Mock()

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 0
        assert result["created_elements"] == []
        assert result["errors"] == []

    def test_query_error_handled(self):
        """Should handle query errors gracefully."""
        graph_manager = Mock()
        graph_manager.query.side_effect = Exception("Connection failed")
        archimate_manager = Mock()
        llm_query_fn = Mock()

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 0
        assert "Query error" in result["errors"][0]

    def test_llm_not_configured(self):
        """Should return error when LLM not configured."""
        graph_manager = Mock()
        graph_manager.query.return_value = [{"name": "test"}]
        archimate_manager = Mock()

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=None,  # No LLM configured
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 0
        assert "LLM not configured" in result["errors"][0]

    def test_llm_error_handled(self):
        """Should handle LLM errors gracefully."""
        graph_manager = Mock()
        graph_manager.query.return_value = [{"name": "test"}]
        archimate_manager = Mock()
        llm_query_fn = Mock(side_effect=Exception("API rate limit"))

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 0
        assert "LLM error" in result["errors"][0]

    def test_successful_element_creation(self):
        """Should create elements from valid LLM response."""
        graph_manager = Mock()
        graph_manager.query.return_value = [{"name": "Core"}]
        archimate_manager = Mock()

        # Mock LLM response with valid elements
        llm_response = Mock()
        llm_response.content = '{"elements": [{"identifier": "comp-core", "name": "Core Component", "documentation": "Core module"}]}'
        llm_query_fn = Mock(return_value=llm_response)

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 1
        assert len(result["created_elements"]) == 1
        assert result["created_elements"][0]["name"] == "Core Component"
        assert result["created_elements"][0]["element_type"] == "ApplicationComponent"
        archimate_manager.add_element.assert_called_once()

    def test_multiple_elements_created(self):
        """Should create multiple elements from LLM response."""
        graph_manager = Mock()
        graph_manager.query.return_value = [{"name": "Core"}, {"name": "Utils"}]
        archimate_manager = Mock()

        llm_response = Mock()
        llm_response.content = '''{"elements": [
            {"identifier": "comp-core", "name": "Core Component"},
            {"identifier": "comp-utils", "name": "Utils Component"}
        ]}'''
        llm_query_fn = Mock(return_value=llm_response)

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 2
        assert len(result["created_elements"]) == 2

    def test_invalid_json_response(self):
        """Should handle invalid JSON response from LLM."""
        graph_manager = Mock()
        graph_manager.query.return_value = [{"name": "test"}]
        archimate_manager = Mock()

        llm_response = Mock()
        llm_response.content = "not valid json"
        llm_query_fn = Mock(return_value=llm_response)

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 0
        assert len(result["errors"]) > 0

    def test_empty_elements_in_response(self):
        """Should handle empty elements array in response."""
        graph_manager = Mock()
        graph_manager.query.return_value = [{"name": "test"}]
        archimate_manager = Mock()

        llm_response = Mock()
        llm_response.content = '{"elements": []}'
        llm_query_fn = Mock(return_value=llm_response)

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 0
        assert result["created_elements"] == []

    def test_element_missing_identifier(self):
        """Should handle elements missing required identifier."""
        graph_manager = Mock()
        graph_manager.query.return_value = [{"name": "test"}]
        archimate_manager = Mock()

        llm_response = Mock()
        llm_response.content = '{"elements": [{"name": "Test Component"}]}'  # Missing identifier
        llm_query_fn = Mock(return_value=llm_response)

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 0
        assert len(result["errors"]) > 0

    def test_element_missing_name(self):
        """Should handle elements missing required name."""
        graph_manager = Mock()
        graph_manager.query.return_value = [{"name": "test"}]
        archimate_manager = Mock()

        llm_response = Mock()
        llm_response.content = '{"elements": [{"identifier": "comp-1"}]}'  # Missing name
        llm_query_fn = Mock(return_value=llm_response)

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 0
        assert len(result["errors"]) > 0

    def test_archimate_manager_error(self):
        """Should handle errors from archimate_manager.add_element."""
        graph_manager = Mock()
        graph_manager.query.return_value = [{"name": "test"}]
        archimate_manager = Mock()
        archimate_manager.add_element.side_effect = Exception("Database error")

        llm_response = Mock()
        llm_response.content = '{"elements": [{"identifier": "comp-1", "name": "Test"}]}'
        llm_query_fn = Mock(return_value=llm_response)

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 0
        assert "Failed to persist" in result["errors"][0]

    def test_response_without_content_attribute(self):
        """Should handle response object without content attribute."""
        graph_manager = Mock()
        graph_manager.query.return_value = [{"name": "test"}]
        archimate_manager = Mock()

        # Response is a string, not an object with .content
        llm_response = '{"elements": [{"identifier": "comp-1", "name": "Test"}]}'
        llm_query_fn = Mock(return_value=llm_response)

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        # Should use str(response) when no .content attribute
        assert result["elements_created"] == 1

    def test_element_with_documentation(self):
        """Should include documentation in created element."""
        graph_manager = Mock()
        graph_manager.query.return_value = [{"name": "test"}]
        archimate_manager = Mock()

        llm_response = Mock()
        llm_response.content = '{"elements": [{"identifier": "comp-1", "name": "Test", "documentation": "This is a test component"}]}'
        llm_query_fn = Mock(return_value=llm_response)

        result = generate_element(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            element_type="ApplicationComponent",
            query="MATCH (n) RETURN n",
            instruction="Create components",
            example="{}",
        )

        assert result["elements_created"] == 1
        # Verify the Element was created with documentation
        call_args = archimate_manager.add_element.call_args
        element = call_args[0][0]
        assert element.documentation == "This is a test component"
