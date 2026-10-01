"""
Pure functions for semantic matching between derived and reference ArchiMate models.

This module provides:
- Parsing of Archi-format .archimate files (reference models)
- Parsing of ArchiMate Exchange Format (Deriva-generated models)
- Element name normalization and similarity scoring
- Matching algorithms for element and relationship comparison
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .types import (
    ReferenceElement,
    ReferenceRelationship,
    SemanticMatch,
    SemanticMatchReport,
)

__all__ = [
    "parse_archi_xml",
    "parse_exchange_format_xml",
    "normalize_element_name",
    "compute_name_similarity",
    "match_element",
    "match_elements",
    "compute_semantic_metrics",
    "create_semantic_match_report",
]

# Namespace prefixes for ArchiMate XML formats
ARCHI_NS = {"archimate": "http://www.archimatetool.com/archimate"}
EXCHANGE_NS = {"": "http://www.opengroup.org/xsd/archimate/3.0/"}
XSI_NS = {"xsi": "http://www.w3.org/2001/XMLSchema-instance"}

# Layer classification by element type prefix
LAYER_MAP = {
    "Business": [
        "BusinessActor",
        "BusinessRole",
        "BusinessCollaboration",
        "BusinessInterface",
        "BusinessProcess",
        "BusinessFunction",
        "BusinessInteraction",
        "BusinessEvent",
        "BusinessService",
        "BusinessObject",
        "Contract",
        "Representation",
        "Product",
    ],
    "Application": [
        "ApplicationComponent",
        "ApplicationCollaboration",
        "ApplicationInterface",
        "ApplicationFunction",
        "ApplicationInteraction",
        "ApplicationProcess",
        "ApplicationEvent",
        "ApplicationService",
        "DataObject",
    ],
    "Technology": [
        "Node",
        "Device",
        "SystemSoftware",
        "TechnologyCollaboration",
        "TechnologyInterface",
        "Path",
        "CommunicationNetwork",
        "TechnologyFunction",
        "TechnologyProcess",
        "TechnologyInteraction",
        "TechnologyEvent",
        "TechnologyService",
        "Artifact",
    ],
    "Strategy": [
        "Resource",
        "Capability",
        "CourseOfAction",
        "ValueStream",
    ],
    "Physical": [
        "Equipment",
        "Facility",
        "DistributionNetwork",
        "Material",
    ],
}


def _get_layer(element_type: str) -> str:
    """Determine the ArchiMate layer for an element type."""
    for layer, types in LAYER_MAP.items():
        if element_type in types:
            return layer
    return ""


def _normalize_type(type_str: str) -> str:
    """
    Normalize element type from XML attribute.

    Handles:
    - "archimate:ApplicationComponent" -> "ApplicationComponent"
    - "ApplicationComponent" -> "ApplicationComponent"
    - "archimate:CompositionRelationship" -> "Composition"
    """
    # Remove archimate: prefix
    if ":" in type_str:
        type_str = type_str.split(":")[-1]

    # Remove "Relationship" suffix for relationship types
    if type_str.endswith("Relationship"):
        type_str = type_str[: -len("Relationship")]

    return type_str


def parse_archi_xml(
    xml_path: str | Path,
) -> tuple[list[ReferenceElement], list[ReferenceRelationship]]:
    """
    Parse an Archi-format .archimate XML file.

    Archi format uses:
    - Namespace: http://www.archimatetool.com/archimate
    - Element type: xsi:type="archimate:ApplicationComponent"
    - Name as attribute: name="Component Name"
    - ID as attribute: id="abc123"
    - Folder structure for organization by layer

    Args:
        xml_path: Path to the .archimate file

    Returns:
        Tuple of (elements, relationships)
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    elements: list[ReferenceElement] = []
    relationships: list[ReferenceRelationship] = []

    # Define namespace mapping
    ns = {
        "archimate": "http://www.archimatetool.com/archimate",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    }

    def _get_xsi_type(elem: ET.Element) -> str:
        """Extract xsi:type attribute."""
        xsi_type = elem.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
        return _normalize_type(xsi_type)

    def _process_folder(folder: ET.Element, layer: str = "") -> None:
        """Recursively process folder and its contents."""
        nonlocal elements, relationships

        # Determine layer from folder type
        folder_type = folder.get("type", "")
        folder_name = folder.get("name", "")

        if folder_type in (
            "business",
            "application",
            "technology",
            "strategy",
            "physical",
        ):
            layer = folder_type.title()
        elif folder_name in (
            "Business",
            "Application",
            "Technology",
            "Strategy",
            "Physical",
        ):
            layer = folder_name

        # Process elements in this folder
        for elem in folder.findall("element", ns):
            if "archimate" in root.tag:
                # Archi format
                elem_type = _get_xsi_type(elem)
                elem_id = elem.get("id", "")
                elem_name = elem.get("name", "")
                doc_elem = elem.find("documentation")
                documentation = doc_elem.text if doc_elem is not None else None
            else:
                continue

            if elem_type and elem_name:
                # Determine layer if not set
                element_layer = layer if layer else _get_layer(elem_type)

                elements.append(
                    ReferenceElement(
                        identifier=elem_id,
                        name=elem_name,
                        element_type=elem_type,
                        layer=element_layer,
                        documentation=documentation,
                    )
                )

        # Process relationships (may be in a separate folder)
        for rel in folder.findall("element", ns):
            rel_type = _get_xsi_type(rel)
            if rel_type and "Relationship" not in rel_type:
                continue  # Skip non-relationship elements

            # Check for relationship-like xsi:type
            xsi_type = rel.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
            if "Relationship" in xsi_type:
                rel_id = rel.get("id", "")
                source = rel.get("source", "")
                target = rel.get("target", "")
                name = rel.get("name")

                relationships.append(
                    ReferenceRelationship(
                        identifier=rel_id,
                        source=source,
                        target=target,
                        relationship_type=_normalize_type(xsi_type),
                        name=name,
                    )
                )

        # Process nested folders
        for nested in folder.findall("folder", ns):
            _process_folder(nested, layer)

    # Handle both Archi format and potential variations
    # Try to find folders at the root level
    for folder in root.findall("folder", ns):
        _process_folder(folder)

    # Also look for direct elements (some Archi exports)
    for elem in root.findall(".//element", ns):
        elem_type = _get_xsi_type(elem)
        # Skip if already processed or if it's a relationship
        if "Relationship" in elem_type:
            continue

        elem_id = elem.get("id", "")
        elem_name = elem.get("name", "")

        # Skip if we already have this element
        if any(e.identifier == elem_id for e in elements):
            continue

        if elem_type and elem_name:
            elements.append(
                ReferenceElement(
                    identifier=elem_id,
                    name=elem_name,
                    element_type=elem_type,
                    layer=_get_layer(elem_type),
                    documentation=None,
                )
            )

    # Look for relationships in relations folder or directly
    for rel in root.findall(".//element", ns):
        xsi_type = rel.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
        if "Relationship" not in xsi_type:
            continue

        rel_id = rel.get("id", "")
        source = rel.get("source", "")
        target = rel.get("target", "")

        # Skip if already processed
        if any(r.identifier == rel_id for r in relationships):
            continue

        relationships.append(
            ReferenceRelationship(
                identifier=rel_id,
                source=source,
                target=target,
                relationship_type=_normalize_type(xsi_type),
                name=rel.get("name"),
            )
        )

    return elements, relationships


def parse_exchange_format_xml(
    xml_path: str | Path,
) -> tuple[list[ReferenceElement], list[ReferenceRelationship]]:
    """
    Parse an ArchiMate Exchange Format XML file (Deriva-generated).

    Exchange format uses:
    - Namespace: http://www.opengroup.org/xsd/archimate/3.0/
    - Element type: xsi:type="ApplicationComponent" (no prefix)
    - Name as child element: <name>Component Name</name>
    - ID as attribute: identifier="abc123"

    Args:
        xml_path: Path to the .archimate file

    Returns:
        Tuple of (elements, relationships)
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    elements: list[ReferenceElement] = []
    relationships: list[ReferenceRelationship] = []

    # Handle namespace in tag matching
    ns_uri = "http://www.opengroup.org/xsd/archimate/3.0/"

    def _tag(name: str) -> str:
        """Create namespaced tag."""
        return f"{{{ns_uri}}}{name}"

    # Find elements section
    elements_section = root.find(_tag("elements"))
    if elements_section is not None:
        for elem in elements_section:
            elem_type = elem.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
            elem_id = elem.get("identifier", "")

            # Get name from child element
            name_elem = elem.find(_tag("name"))
            elem_name = name_elem.text if name_elem is not None else ""

            # Get documentation
            doc_elem = elem.find(_tag("documentation"))
            documentation = doc_elem.text if doc_elem is not None else None

            if elem_type and elem_name:
                elements.append(
                    ReferenceElement(
                        identifier=elem_id,
                        name=elem_name,
                        element_type=elem_type,
                        layer=_get_layer(elem_type),
                        documentation=documentation,
                    )
                )

    # Find relationships section
    relationships_section = root.find(_tag("relationships"))
    if relationships_section is not None:
        for rel in relationships_section:
            rel_type = rel.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
            rel_id = rel.get("identifier", "")
            source = rel.get("source", "")
            target = rel.get("target", "")

            # Get name from child element
            name_elem = rel.find(_tag("name"))
            name = name_elem.text if name_elem is not None else None

            relationships.append(
                ReferenceRelationship(
                    identifier=rel_id,
                    source=source,
                    target=target,
                    relationship_type=rel_type,
                    name=name,
                )
            )

    return elements, relationships


def normalize_element_name(name: str) -> str:
    """
    Normalize an element name for comparison.

    Transformations:
    - Convert to lowercase
    - Split camelCase and PascalCase into words
    - Remove special characters
    - Collapse whitespace
    - Strip leading/trailing whitespace

    Args:
        name: Raw element name

    Returns:
        Normalized name for comparison
    """
    if not name:
        return ""

    # Convert to lowercase
    result = name.lower()

    # Split camelCase/PascalCase: "CRUDController" -> "crud controller"
    result = re.sub(r"([a-z])([A-Z])", r"\1 \2", result)
    result = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", result)

    # Replace underscores and hyphens with spaces
    result = re.sub(r"[_\-]", " ", result)

    # Remove special characters except spaces
    result = re.sub(r"[^a-z0-9\s]", "", result)

    # Collapse multiple spaces
    result = re.sub(r"\s+", " ", result)

    # Strip
    return result.strip()


def compute_name_similarity(name1: str, name2: str) -> float:
    """
    Compute semantic similarity between two element names.

    Scoring:
    - Exact match (after normalization): 1.0
    - High sequence similarity: 0.7-0.99
    - Token overlap bonus: up to 0.2 additional

    Args:
        name1: First element name
        name2: Second element name

    Returns:
        Similarity score (0.0 to 1.0)
    """
    # Normalize both names
    norm1 = normalize_element_name(name1)
    norm2 = normalize_element_name(name2)

    if not norm1 or not norm2:
        return 0.0

    # Exact match after normalization
    if norm1 == norm2:
        return 1.0

    # Sequence similarity (Levenshtein-based)
    sequence_sim = SequenceMatcher(None, norm1, norm2).ratio()

    # Token overlap
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())

    if tokens1 and tokens2:
        intersection = tokens1 & tokens2
        union = tokens1 | tokens2
        token_overlap = len(intersection) / len(union) if union else 0.0
    else:
        token_overlap = 0.0

    # Combined score: weighted average
    # Sequence similarity is primary (0.7 weight), token overlap is bonus (0.3 weight)
    combined = 0.7 * sequence_sim + 0.3 * token_overlap

    return min(combined, 1.0)


def match_element(
    derived_id: str,
    derived_name: str,
    derived_type: str,
    reference_elements: list[ReferenceElement],
    type_weight: float = 0.3,
    name_weight: float = 0.7,
    threshold: float = 0.3,
) -> SemanticMatch:
    """
    Find the best match for a derived element in the reference model.

    Matching strategy:
    1. Exact name + exact type -> score 1.0
    2. Fuzzy name + exact type -> higher score
    3. Exact name + compatible type -> medium score
    4. Fuzzy name + different type -> lower score
    5. No reasonable match -> no_match

    Args:
        derived_id: Derived element identifier
        derived_name: Derived element name
        derived_type: Derived element type
        reference_elements: List of reference elements to match against
        type_weight: Weight for type match (default 0.3)
        name_weight: Weight for name match (default 0.7)
        threshold: Minimum score to consider a match (default 0.3)

    Returns:
        SemanticMatch with best match details
    """
    best_match: SemanticMatch | None = None
    best_score = 0.0

    for ref in reference_elements:
        # Compute name similarity
        name_sim = compute_name_similarity(derived_name, ref.name)

        # Compute type similarity (binary: 1.0 if match, 0.0 otherwise)
        type_sim = 1.0 if derived_type == ref.element_type else 0.0

        # Check for compatible types (same layer)
        if type_sim == 0.0:
            derived_layer = _get_layer(derived_type)
            ref_layer = ref.layer or _get_layer(ref.element_type)
            if derived_layer and derived_layer == ref_layer:
                type_sim = 0.5  # Partial type match for same-layer elements

        # Combined score
        score = name_weight * name_sim + type_weight * type_sim

        # Determine match type
        if name_sim >= 0.95 and type_sim == 1.0:
            match_type = "exact"
        elif name_sim >= 0.5 and type_sim >= 0.5:
            match_type = "fuzzy_name"
        elif name_sim >= 0.8 and type_sim < 0.5:
            match_type = "type_mismatch"
        elif type_sim == 1.0 and name_sim >= 0.3:
            match_type = "type_only"
        else:
            match_type = "weak"

        if score > best_score:
            best_score = score
            best_match = SemanticMatch(
                derived_id=derived_id,
                derived_name=derived_name,
                derived_type=derived_type,
                reference_id=ref.identifier,
                reference_name=ref.name,
                reference_type=ref.element_type,
                match_type=match_type,
                similarity_score=score,
            )

    # If no match above threshold, return no_match
    if best_match is None or best_score < threshold:
        return SemanticMatch(
            derived_id=derived_id,
            derived_name=derived_name,
            derived_type=derived_type,
            reference_id=None,
            reference_name=None,
            reference_type=None,
            match_type="no_match",
            similarity_score=0.0,
        )

    return best_match


def match_elements(
    derived_elements: list[dict[str, Any]],
    reference_elements: list[ReferenceElement],
    threshold: float = 0.3,
) -> list[SemanticMatch]:
    """
    Match all derived elements against reference elements.

    Args:
        derived_elements: List of derived elements (dicts with id, name, type)
        reference_elements: List of reference elements
        threshold: Minimum score to consider a match

    Returns:
        List of SemanticMatch objects
    """
    matches = []

    for derived in derived_elements:
        derived_id = derived.get("id", derived.get("identifier", ""))
        derived_name = derived.get("name", "")
        derived_type = derived.get("type", derived.get("element_type", ""))

        match = match_element(
            derived_id=derived_id,
            derived_name=derived_name,
            derived_type=derived_type,
            reference_elements=reference_elements,
            threshold=threshold,
        )
        matches.append(match)

    return matches


def compute_semantic_metrics(
    matches: list[SemanticMatch],
    total_reference: int,
) -> dict[str, float]:
    """
    Compute precision, recall, and F1 score from matches.

    Args:
        matches: List of SemanticMatch objects
        total_reference: Total number of reference elements

    Returns:
        Dict with precision, recall, f1 scores
    """
    if not matches:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    # Count matches (not no_match)
    matched = [m for m in matches if m.match_type != "no_match"]
    correctly_derived = len(matched)
    total_derived = len(matches)

    # Precision: correctly_derived / total_derived
    precision = correctly_derived / total_derived if total_derived > 0 else 0.0

    # Recall: correctly_derived / total_reference
    recall = correctly_derived / total_reference if total_reference > 0 else 0.0

    # F1 score
    if precision + recall > 0:
        f1 = 2 * (precision * recall) / (precision + recall)
    else:
        f1 = 0.0

    return {"precision": precision, "recall": recall, "f1": f1}


def create_semantic_match_report(
    repository: str,
    reference_model_path: str,
    derived_run: str,
    derived_elements: list[dict[str, Any]],
    reference_elements: list[ReferenceElement],
    derived_relationships: list[dict[str, Any]] | None = None,
    reference_relationships: list[ReferenceRelationship] | None = None,
    threshold: float = 0.3,
) -> SemanticMatchReport:
    """
    Create a complete semantic match report.

    Args:
        repository: Repository name
        reference_model_path: Path to reference model
        derived_run: Run identifier
        derived_elements: List of derived elements
        reference_elements: List of reference elements
        derived_relationships: Optional list of derived relationships
        reference_relationships: Optional list of reference relationships
        threshold: Minimum score for a match

    Returns:
        SemanticMatchReport with all metrics
    """
    # Match elements
    element_matches = match_elements(derived_elements, reference_elements, threshold)

    # Categorize matches
    correctly_derived = [m for m in element_matches if m.match_type != "no_match"]
    spurious_elements = [m.derived_id for m in element_matches if m.match_type == "no_match"]

    # Find missing elements (reference elements not matched)
    matched_ref_ids = {m.reference_id for m in correctly_derived if m.reference_id}
    missing_elements = [e for e in reference_elements if e.identifier not in matched_ref_ids]

    # Compute metrics
    element_metrics = compute_semantic_metrics(element_matches, len(reference_elements))

    # Handle relationships if provided
    rel_metrics = {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    correctly_derived_rels: list[SemanticMatch] = []
    missing_rels: list[ReferenceRelationship] = []
    spurious_rels: list[str] = []

    if derived_relationships and reference_relationships:
        # TODO: Implement relationship matching
        # For now, simple ID-based matching
        derived_rel_ids = {r.get("id", "") for r in derived_relationships}
        ref_rel_ids = {r.identifier for r in reference_relationships}

        overlap = derived_rel_ids & ref_rel_ids
        rel_precision = len(overlap) / len(derived_rel_ids) if derived_rel_ids else 0.0
        rel_recall = len(overlap) / len(ref_rel_ids) if ref_rel_ids else 0.0
        rel_f1 = 2 * rel_precision * rel_recall / (rel_precision + rel_recall) if rel_precision + rel_recall > 0 else 0.0
        rel_metrics = {"precision": rel_precision, "recall": rel_recall, "f1": rel_f1}

    return SemanticMatchReport(
        repository=repository,
        reference_model_path=reference_model_path,
        derived_run=derived_run,
        total_derived_elements=len(derived_elements),
        total_reference_elements=len(reference_elements),
        correctly_derived=correctly_derived,
        missing_elements=missing_elements,
        spurious_elements=spurious_elements,
        total_derived_relationships=len(derived_relationships) if derived_relationships else 0,
        total_reference_relationships=len(reference_relationships) if reference_relationships else 0,
        correctly_derived_relationships=correctly_derived_rels,
        missing_relationships=missing_rels,
        spurious_relationships=spurious_rels,
        element_precision=element_metrics["precision"],
        element_recall=element_metrics["recall"],
        element_f1=element_metrics["f1"],
        relationship_precision=rel_metrics["precision"],
        relationship_recall=rel_metrics["recall"],
        relationship_f1=rel_metrics["f1"],
    )
