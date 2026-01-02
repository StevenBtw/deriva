"""Basic tests for ArchiMate Manager.

To run these tests, you must have Neo4j running:
    cd neo4j_manager
    docker-compose up -d

Then run:
    pytest tests/test_managers/archimate/test_archimate_manager.py -m integration
"""

import pytest

# Mark integration tests; run with: pytest -m integration
pytestmark = pytest.mark.integration

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Element, Relationship
from deriva.adapters.archimate.validation import ValidationError
from deriva.adapters.archimate.xml_export import ArchiMateXMLExporter


@pytest.fixture
def archimate_manager():
    """Create an ArchimateManager instance for testing."""
    manager = ArchimateManager()
    manager.connect()

    # Clear any existing data
    try:
        manager.clear_model()
    except Exception:
        pass  # Might fail if database is empty

    yield manager

    # Cleanup
    try:
        manager.clear_model()
    except Exception:
        pass
    manager.disconnect()


def test_connect_disconnect():
    """Test basic connection and disconnection."""
    manager = ArchimateManager()
    manager.connect()
    assert manager.neo4j is not None
    manager.disconnect()
    assert manager.neo4j is None


def test_context_manager():
    """Test using ArchimateManager as context manager."""
    with ArchimateManager() as manager:
        assert manager.neo4j is not None
    # After context, should be disconnected
    assert manager.neo4j is None


def test_add_element(archimate_manager):
    """Test adding an element."""
    element = Element(name="Test Component", element_type="ApplicationComponent", documentation="A test application component")

    element_id = archimate_manager.add_element(element)
    assert element_id == element.identifier

    # Retrieve and verify
    retrieved = archimate_manager.get_element(element_id)
    assert retrieved is not None
    assert retrieved.name == "Test Component"
    assert retrieved.element_type == "ApplicationComponent"
    assert retrieved.documentation == "A test application component"


def test_add_multiple_elements(archimate_manager):
    """Test adding multiple elements."""
    e1 = Element("Component 1", "ApplicationComponent")
    e2 = Element("Component 2", "ApplicationComponent")
    e3 = Element("Service 1", "ApplicationService")

    archimate_manager.add_element(e1)
    archimate_manager.add_element(e2)
    archimate_manager.add_element(e3)

    all_elements = archimate_manager.get_elements()
    assert len(all_elements) == 3

    # Filter by type
    components = archimate_manager.get_elements(element_type="ApplicationComponent")
    assert len(components) == 2

    services = archimate_manager.get_elements(element_type="ApplicationService")
    assert len(services) == 1


def test_add_relationship(archimate_manager):
    """Test adding a relationship."""
    # Create two elements
    e1 = Element("Parent", "ApplicationComponent")
    e2 = Element("Child", "ApplicationComponent")

    archimate_manager.add_element(e1)
    archimate_manager.add_element(e2)

    # Create relationship
    rel = Relationship(source=e1.identifier, target=e2.identifier, relationship_type="Composition")

    rel_id = archimate_manager.add_relationship(rel)
    assert rel_id == rel.identifier

    # Retrieve relationships
    relationships = archimate_manager.get_relationships(source_id=e1.identifier)
    assert len(relationships) == 1
    assert relationships[0].source == e1.identifier
    assert relationships[0].target == e2.identifier


def test_element_validation(archimate_manager):
    """Test element validation."""
    # Invalid element type
    invalid_element = Element("Test", "InvalidType")

    with pytest.raises(ValidationError):
        archimate_manager.add_element(invalid_element)


def test_clear_model(archimate_manager):
    """Test clearing the model."""
    # Add some data
    e1 = Element("Test 1", "ApplicationComponent")
    e2 = Element("Test 2", "ApplicationComponent")
    archimate_manager.add_element(e1)
    archimate_manager.add_element(e2)

    assert len(archimate_manager.get_elements()) == 2

    # Clear
    archimate_manager.clear_model()

    assert len(archimate_manager.get_elements()) == 0


def test_xml_export(archimate_manager, tmp_path):
    """Test XML export functionality."""
    # Create a simple model
    e1 = Element("Component A", "ApplicationComponent")
    e2 = Element("Component B", "ApplicationComponent")
    archimate_manager.add_element(e1)
    archimate_manager.add_element(e2)

    rel = Relationship(e1.identifier, e2.identifier, "Composition")
    archimate_manager.add_relationship(rel)

    # Export to XML
    output_file = tmp_path / "test_model.xml"
    exporter = ArchiMateXMLExporter()

    elements = archimate_manager.get_elements()
    relationships = archimate_manager.get_relationships()

    exporter.export(elements, relationships, str(output_file), model_name="Test Model")

    # Verify file was created
    assert output_file.exists()

    # Read and verify XML content
    content = output_file.read_text()
    assert "Component A" in content
    assert "Component B" in content
    assert "Composition" in content
    assert "Test Model" in content


def test_element_properties(archimate_manager):
    """Test element with custom properties."""
    element = Element(name="Test", element_type="ApplicationComponent", properties={"version": "1.0", "owner": "Team A"})

    archimate_manager.add_element(element)
    retrieved = archimate_manager.get_element(element.identifier)

    assert retrieved.properties["version"] == "1.0"
    assert retrieved.properties["owner"] == "Team A"


@pytest.mark.integration
def test_cypher_query(archimate_manager):
    """Test custom Cypher query."""
    # Add some elements
    e1 = Element("Component 1", "ApplicationComponent")
    e2 = Element("Component 2", "ApplicationComponent")
    archimate_manager.add_element(e1)
    archimate_manager.add_element(e2)

    # Custom query to count elements (namespace-aware label)
    # Elements are created with their type as label (e.g., Model:ApplicationComponent)
    assert archimate_manager.neo4j is not None
    element_label = archimate_manager.neo4j.get_label("ApplicationComponent")
    query = f"""
        MATCH (e:`{element_label}`)
        RETURN count(e) as element_count
    """

    result = archimate_manager.query(query)
    assert len(result) == 1
    assert result[0]["element_count"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
