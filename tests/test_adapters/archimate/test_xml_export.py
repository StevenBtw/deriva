"""Tests for adapters.archimate.xml_export module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from deriva.adapters.archimate.models import Element, Relationship
from deriva.adapters.archimate.xml_export import ArchiMateXMLExporter


class TestArchiMateXMLExporter:
    """Tests for ArchiMateXMLExporter class."""

    @pytest.fixture
    def exporter(self):
        """Create exporter instance."""
        return ArchiMateXMLExporter()

    @pytest.fixture
    def sample_element(self):
        """Create sample element."""
        return Element(
            identifier="elem-1",
            name="UserService",
            element_type="ApplicationService",
            documentation="Handles user operations",
        )

    @pytest.fixture
    def sample_relationship(self):
        """Create sample relationship."""
        return Relationship(
            identifier="rel-1",
            relationship_type="ServingRelationship",
            source="elem-1",
            target="elem-2",
            name="serves",
        )

    def test_export_to_string_returns_xml(self, exporter, sample_element):
        """Should return valid XML string."""
        result = exporter.export_to_string([sample_element], [])
        assert "<?xml version=" in result
        assert "<model" in result
        assert "UserService" in result

    def test_export_to_string_includes_elements(self, exporter, sample_element):
        """Should include element in XML."""
        result = exporter.export_to_string([sample_element], [])
        assert 'identifier="elem-1"' in result
        assert "ApplicationService" in result

    def test_export_to_string_includes_relationships(self, exporter, sample_element, sample_relationship):
        """Should include relationship in XML."""
        result = exporter.export_to_string([sample_element], [sample_relationship])
        assert 'identifier="rel-1"' in result
        assert "ServingRelationship" in result

    def test_export_to_string_with_empty_inputs(self, exporter):
        """Should handle empty elements and relationships."""
        result = exporter.export_to_string([], [])
        assert "<?xml version=" in result
        assert "<model" in result

    def test_export_writes_file(self, exporter, sample_element):
        """Should write XML to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "model.archimate"
            exporter.export([sample_element], [], str(output_path))

            assert output_path.exists()
            content = output_path.read_text()
            assert "UserService" in content

    def test_export_creates_parent_directories(self, exporter, sample_element):
        """Should create parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "subdir" / "nested" / "model.archimate"
            exporter.export([sample_element], [], str(output_path))

            assert output_path.exists()

    def test_export_with_custom_model_name(self, exporter, sample_element):
        """Should use custom model name."""
        result = exporter.export_to_string([sample_element], [], model_name="My Custom Model")
        assert "My Custom Model" in result

    def test_export_includes_metadata(self, exporter):
        """Should include metadata section."""
        result = exporter.export_to_string([], [])
        assert "<metadata>" in result
        assert "Dublin Core" in result
        assert "Deriva" in result
