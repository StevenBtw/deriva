"""Tests for adapters.graph.metamodel module."""

from __future__ import annotations

from deriva.adapters.graph.metamodel import (
    get_all_node_classes,
    get_metamodel,
    get_node_order,
    get_node_properties,
    get_relationship_types,
)


class TestGetAllNodeClasses:
    """Tests for get_all_node_classes function."""

    def test_returns_dict_of_classes(self):
        """Should return dictionary of node classes."""
        classes = get_all_node_classes()
        assert isinstance(classes, dict)
        assert len(classes) > 0

    def test_includes_expected_node_types(self):
        """Should include common node types."""
        classes = get_all_node_classes()
        # These are common node types that should exist
        expected = ["Repository", "File", "Directory", "Module"]
        for node_type in expected:
            assert node_type in classes, f"Missing {node_type}"

    def test_values_are_classes(self):
        """Should map to class types."""
        classes = get_all_node_classes()
        for node_type, cls in classes.items():
            assert isinstance(cls, type)


class TestGetNodeProperties:
    """Tests for get_node_properties function."""

    def test_returns_list_of_properties(self):
        """Should return list of property names."""
        classes = get_all_node_classes()
        if classes:
            node_class = next(iter(classes.values()))
            props = get_node_properties(node_class)
            assert isinstance(props, list)
            assert len(props) > 0
            assert all(isinstance(p, str) for p in props)


class TestGetRelationshipTypes:
    """Tests for get_relationship_types function."""

    def test_returns_list_of_strings(self):
        """Should return list of relationship type strings."""
        types = get_relationship_types()
        assert isinstance(types, list)
        assert all(isinstance(t, str) for t in types)

    def test_returns_sorted_list(self):
        """Should return sorted list."""
        types = get_relationship_types()
        assert types == sorted(types)


class TestGetMetamodel:
    """Tests for get_metamodel function."""

    def test_returns_dict_with_nodes_and_relationships(self):
        """Should return dict with nodes and relationships keys."""
        metamodel = get_metamodel()
        assert "nodes" in metamodel
        assert "relationships" in metamodel

    def test_nodes_have_expected_structure(self):
        """Should have nodes with expected structure."""
        metamodel = get_metamodel()
        if metamodel["nodes"]:
            node = metamodel["nodes"][0]
            assert "name" in node
            assert "class" in node
            assert "properties" in node

    def test_relationships_have_name_and_description(self):
        """Should have relationships with name and description."""
        metamodel = get_metamodel()
        if metamodel["relationships"]:
            rel = metamodel["relationships"][0]
            assert "name" in rel
            assert "description" in rel


class TestGetNodeOrder:
    """Tests for get_node_order function."""

    def test_returns_list_of_strings(self):
        """Should return list of node type names."""
        order = get_node_order()
        assert isinstance(order, list)
        assert all(isinstance(n, str) for n in order)

    def test_starts_with_repository(self):
        """Should start with Repository."""
        order = get_node_order()
        assert order[0] == "Repository"

    def test_includes_common_types(self):
        """Should include common node types."""
        order = get_node_order()
        expected = ["Repository", "File", "Directory"]
        for node_type in expected:
            assert node_type in order
