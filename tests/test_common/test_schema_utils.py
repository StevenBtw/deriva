"""Tests for common.schema_utils module."""

from __future__ import annotations

from deriva.common.schema_utils import build_array_schema, build_object_schema


class TestBuildArraySchema:
    """Tests for build_array_schema function."""

    def test_builds_basic_schema(self):
        """Should build schema with required structure."""
        schema = build_array_schema(
            name="test_output",
            array_key="items",
            item_properties={"name": {"type": "string"}},
            required_item_fields=["name"],
        )

        assert schema["name"] == "test_output"
        assert schema["strict"] is True
        assert schema["schema"]["type"] == "object"
        assert "items" in schema["schema"]["properties"]

    def test_includes_array_items(self):
        """Should define array items correctly."""
        schema = build_array_schema(
            name="output",
            array_key="elements",
            item_properties={
                "id": {"type": "string"},
                "value": {"type": "number"},
            },
            required_item_fields=["id"],
        )

        items_schema = schema["schema"]["properties"]["elements"]["items"]
        assert items_schema["type"] == "object"
        assert "id" in items_schema["properties"]
        assert "value" in items_schema["properties"]
        assert items_schema["required"] == ["id"]

    def test_sets_additional_properties(self):
        """Should set additionalProperties based on parameter."""
        schema_allow = build_array_schema(
            name="output",
            array_key="items",
            item_properties={},
            required_item_fields=[],
            allow_additional_properties=True,
        )
        assert schema_allow["schema"]["properties"]["items"]["items"]["additionalProperties"] is True

        schema_deny = build_array_schema(
            name="output",
            array_key="items",
            item_properties={},
            required_item_fields=[],
            allow_additional_properties=False,
        )
        assert schema_deny["schema"]["properties"]["items"]["items"]["additionalProperties"] is False

    def test_requires_array_key(self):
        """Should mark array key as required."""
        schema = build_array_schema(
            name="output",
            array_key="results",
            item_properties={},
            required_item_fields=[],
        )

        assert schema["schema"]["required"] == ["results"]


class TestBuildObjectSchema:
    """Tests for build_object_schema function."""

    def test_builds_basic_schema(self):
        """Should build schema with required structure."""
        schema = build_object_schema(
            name="summary_output",
            properties={"summary": {"type": "string"}},
            required_fields=["summary"],
        )

        assert schema["name"] == "summary_output"
        assert schema["strict"] is True
        assert schema["schema"]["type"] == "object"

    def test_includes_properties(self):
        """Should include all properties."""
        schema = build_object_schema(
            name="output",
            properties={
                "title": {"type": "string"},
                "count": {"type": "integer"},
                "active": {"type": "boolean"},
            },
            required_fields=["title"],
        )

        props = schema["schema"]["properties"]
        assert "title" in props
        assert "count" in props
        assert "active" in props

    def test_sets_required_fields(self):
        """Should set required fields."""
        schema = build_object_schema(
            name="output",
            properties={"a": {}, "b": {}, "c": {}},
            required_fields=["a", "b"],
        )

        assert schema["schema"]["required"] == ["a", "b"]

    def test_disallows_additional_properties(self):
        """Should disallow additional properties."""
        schema = build_object_schema(
            name="output",
            properties={},
            required_fields=[],
        )

        assert schema["schema"]["additionalProperties"] is False
