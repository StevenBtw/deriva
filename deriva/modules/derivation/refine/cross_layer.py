"""
Cross-Layer Coherence - Refine Step.

Validates ArchiMate cross-layer relationships follow proper patterns:
- Business Layer elements should connect to Application Layer
- Application Layer elements should connect to Technology Layer
- Detects "floating" elements with no cross-layer connections

ArchiMate Layers:
- Business: BusinessObject, BusinessProcess, BusinessActor, BusinessEvent, BusinessFunction
- Application: ApplicationComponent, ApplicationService, ApplicationInterface, DataObject
- Technology: TechnologyService, Node, Device, SystemSoftware

Refine Step Name: "cross_layer"
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from deriva.common.naming import _words, singularize

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)
    from deriva.adapters.graph import GraphManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)

logger = logging.getLogger(__name__)

# ArchiMate layer definitions
BUSINESS_LAYER = {
    "BusinessObject",
    "BusinessProcess",
    "BusinessActor",
    "BusinessEvent",
    "BusinessFunction",
}

APPLICATION_LAYER = {
    "ApplicationComponent",
    "ApplicationService",
    "ApplicationInterface",
    "DataObject",
}

TECHNOLOGY_LAYER = {
    "TechnologyService",
    "Node",
    "Device",
    "SystemSoftware",
}

# Valid cross-layer relationship types
VALID_CROSS_LAYER_RELS = {
    "Realization",
    "Serving",
    "Access",
    "Flow",
    "Triggering",
    "Association",
}

LAYERS = {"Business": BUSINESS_LAYER, "Application": APPLICATION_LAYER, "Technology": TECHNOLOGY_LAYER}


def unanchored(element_types: dict[str, str], links: Iterable[tuple[str, str]], layers: Iterable[str]) -> list[str]:
    """Elements of the given layers without a link to another layer, directly or through links within their layer.

    Args:
        element_types: Element identifier -> ArchiMate type (the elements that count; links to others are ignored)
        links: (source, target) identifier pairs, direction ignored
        layers: Layer names (keys of LAYERS) whose elements need an anchor

    Returns:
        Sorted identifiers of the unanchored elements
    """
    layer_of = {element_type: name for name, types in LAYERS.items() for element_type in types}
    listed = set(layers)
    candidates = {i for i, t in element_types.items() if layer_of.get(t) in listed}
    pairs = [(s, t) for s, t in links if s in element_types and t in element_types]
    anchored = {a for s, t in pairs for a, b in ((s, t), (t, s)) if a in candidates and layer_of.get(element_types[b]) != layer_of.get(element_types[a])}
    changed = True
    while changed:
        changed = False
        for s, t in pairs:
            if s in candidates and t in candidates and (s in anchored) != (t in anchored):
                anchored |= {s, t}
                changed = True
    return sorted(candidates - anchored)


def _name_words(name: str) -> tuple[str, ...]:
    return tuple(singularize(w.lower()) for w in _words(name or "") if w)


def _in_a_row(words: tuple[str, ...], part: tuple[str, ...]) -> bool:
    return any(words[i : i + len(part)] == part for i in range(len(words) - len(part) + 1))


def code_supported(names: dict[str, str], code_names: Iterable[str], multi_word_names: int, single_word_names: int | None) -> set[str]:
    """Identifiers whose name's words appear in a row in enough distinct code names (type definition and
    directory names): `multi_word_names` for a name of two or more words, `single_word_names` for one word
    (None: a single word never counts)."""
    code = [words for words in {_name_words(n) for n in code_names} if words]
    supported = set()
    for identifier, name in names.items():
        words = _name_words(name)
        needed = multi_word_names if len(words) > 1 else single_word_names
        if words and needed is not None and sum(1 for c in code if _in_a_row(c, words)) >= needed:
            supported.add(identifier)
    return supported


_CODE_NAME_QUERIES = (
    "MATCH (t:Graph:TypeDefinition) WHERE t.category <> 'external_reference' RETURN DISTINCT t.typeName AS name",
    "MATCH (d:Graph:Directory) RETURN DISTINCT d.name AS name",
)


def _code_names(graph_manager: GraphManager) -> list[str]:
    """The repository's own type definition names and its directory names."""
    return [row["name"] for query in _CODE_NAME_QUERIES for row in graph_manager.query(query) if row.get("name")]


@register_refine_step("cross_layer_coherence")
class CrossLayerCoherenceStep:
    """Validate ArchiMate cross-layer coherence."""

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        """Execute cross-layer coherence validation.

        Args:
            archimate_manager: Manager for ArchiMate model operations
            graph_manager: Source graph, for the code names of `code_support`
            llm_query_fn: Not used for this step
            params: Optional parameters:
                - check_business_to_app: Validate Business→App connections (default: True)
                - check_app_to_tech: Validate App→Tech connections (default: True)
                - strict_mode: Fail on any violations (default: False)
                - disable_unanchored: Layers (Business, Application, Technology) whose elements are disabled
                  when they have no link to another layer, directly or through their own layer (default: none)
                - code_support: {"multi_word_names": n, "single_word_names": m}: an unanchored element stays
                  when the words of its source's name appear in a row in at least n (m for one word, null: a
                  single word never counts) distinct type definition or directory names (default: no code support)

        Returns:
            RefineResult with details of cross-layer issues found
        """
        params = params or {}
        check_business_to_app = params.get("check_business_to_app", True)
        check_app_to_tech = params.get("check_app_to_tech", True)
        disable_unanchored = params.get("disable_unanchored", [])
        code_support = params.get("code_support")

        result = RefineResult(
            success=True,
            step_name="cross_layer_coherence",
        )

        if not isinstance(disable_unanchored, list) or any(layer not in LAYERS for layer in disable_unanchored):
            result.success = False
            result.errors.append(f"params.disable_unanchored must be a list of {sorted(LAYERS)}, got {disable_unanchored!r}")
            return result
        support_keys = ("multi_word_names", "single_word_names")

        def count(value: Any, optional: bool) -> bool:
            return (optional and value is None) or (isinstance(value, int) and not isinstance(value, bool) and value >= 1)

        if code_support is not None and not (
            isinstance(code_support, dict)
            and set(code_support) == set(support_keys)
            and count(code_support["multi_word_names"], optional=False)
            and count(code_support["single_word_names"], optional=True)
            and graph_manager is not None
        ):
            result.success = False
            result.errors.append(
                f"params.code_support must be {{{', '.join(support_keys)}}} with counts of at least 1 (single_word_names may be null) "
                f"and needs the source graph, got {code_support!r}"
            )
            return result

        try:
            ns = archimate_manager.namespace

            if disable_unanchored:
                self._disable_unanchored(archimate_manager, result, disable_unanchored, graph_manager, code_support)

            # Check Business Layer → Application Layer connections
            if check_business_to_app:
                self._check_layer_connections(
                    archimate_manager,
                    result,
                    source_layer="Business",
                    source_types=BUSINESS_LAYER,
                    target_layer="Application",
                    target_types=APPLICATION_LAYER,
                    ns=ns,
                )

            # Check Application Layer → Technology Layer connections
            if check_app_to_tech:
                self._check_layer_connections(
                    archimate_manager,
                    result,
                    source_layer="Application",
                    source_types=APPLICATION_LAYER,
                    target_layer="Technology",
                    target_types=TECHNOLOGY_LAYER,
                    ns=ns,
                )

            # Check for floating Technology elements (no connections to App)
            self._check_floating_elements(
                archimate_manager,
                result,
                layer="Technology",
                types=TECHNOLOGY_LAYER,
                connected_to="Application",
                connected_types=APPLICATION_LAYER,
                ns=ns,
            )

            logger.info(f"Cross-layer coherence check complete: {result.issues_found} issues found")

        except Exception as e:
            logger.exception(f"Error in cross-layer coherence check: {e}")
            result.success = False
            result.errors.append(str(e))

        return result

    def _disable_unanchored(
        self,
        archimate_manager: ArchimateManager,
        result: RefineResult,
        layers: list[str],
        graph_manager: GraphManager | None = None,
        code_support: dict[str, int] | None = None,
    ) -> None:
        """Disable the enabled elements of the given layers that have no anchor in another layer and, with
        `code_support`, whose source's name the code does not carry."""
        elements = {e.identifier: e for e in archimate_manager.get_elements(enabled_only=True)}
        links = [(r.source, r.target) for r in archimate_manager.get_relationships()]
        identifiers = unanchored({i: e.element_type for i, e in elements.items()}, links, layers)
        if identifiers and code_support and graph_manager is not None:
            sources = {i: (elements[i].properties or {}).get("source") for i in identifiers}
            rows = graph_manager.query("MATCH (n) WHERE n.id IN $ids RETURN n.id AS id, n.conceptName AS name", {"ids": sorted({s for s in sources.values() if s})})
            source_names = {row["id"]: row["name"] for row in rows if row.get("name")}
            names = {i: source_names.get(sources[i] or "", elements[i].name) for i in identifiers}
            kept = code_supported(names, _code_names(graph_manager), code_support["multi_word_names"], code_support["single_word_names"])
            for identifier in sorted(kept):
                element = elements[identifier]
                result.details.append({"action": "kept", "identifier": identifier, "name": element.name, "element_type": element.element_type, "reason": "code_support"})
            identifiers = [i for i in identifiers if i not in kept]
        if not identifiers:
            return
        archimate_manager.disable_elements(identifiers, reason="no_cross_layer_anchor")
        logger.info("Disabled %d elements without a cross-layer anchor (%s)", len(identifiers), ", ".join(layers))
        result.elements_disabled += len(identifiers)
        result.issues_fixed += len(identifiers)
        for identifier in identifiers:
            element = elements[identifier]
            result.details.append(
                {
                    "action": "disabled",
                    "identifier": identifier,
                    "name": element.name,
                    "element_type": element.element_type,
                    "reason": "no_cross_layer_anchor",
                }
            )

    def _check_layer_connections(
        self,
        archimate_manager: ArchimateManager,
        result: RefineResult,
        source_layer: str,
        source_types: set[str],
        target_layer: str,
        target_types: set[str],
        ns: str,
    ) -> None:
        """Check that source layer elements have connections to target layer."""
        # Build type labels for query
        source_labels = [f"{ns}:{t}" for t in source_types]
        target_labels = [f"{ns}:{t}" for t in target_types]

        # Query for source elements without any connection to target layer
        # This query finds elements that have NO relationship to any target layer element
        query = f"""
            MATCH (source)
            WHERE any(lbl IN labels(source) WHERE lbl IN {source_labels})
              AND source.enabled = true
            WITH source
            WHERE NOT EXISTS {{
                MATCH (source)-[r]-(target)
                WHERE any(lbl IN labels(target) WHERE lbl IN {target_labels})
                  AND type(r) STARTS WITH '{ns}:'
            }}
            RETURN source.identifier as identifier,
                   source.name as name,
                   [lbl IN labels(source) WHERE lbl <> '{ns}'][0] as label
        """

        disconnected = archimate_manager.query(query)

        if disconnected:
            logger.info(f"Found {len(disconnected)} {source_layer} elements without {target_layer} connections")

            for elem in disconnected:
                element_type = elem["label"] if elem["label"] else "Unknown"
                result.issues_found += 1
                result.details.append(
                    {
                        "action": "flagged",
                        "identifier": elem["identifier"],
                        "name": elem["name"],
                        "element_type": element_type,
                        "source_layer": source_layer,
                        "missing_connection_to": target_layer,
                        "reason": f"no_{target_layer.lower()}_layer_connection",
                    }
                )

    def _check_floating_elements(
        self,
        archimate_manager: ArchimateManager,
        result: RefineResult,
        layer: str,
        types: set[str],
        connected_to: str,
        connected_types: set[str],
        ns: str,
    ) -> None:
        """Check for elements with no connections to higher layer.

        Technology elements should ideally support Application elements.
        """
        type_labels = [f"{ns}:{t}" for t in types]
        connected_labels = [f"{ns}:{t}" for t in connected_types]

        query = f"""
            MATCH (elem)
            WHERE any(lbl IN labels(elem) WHERE lbl IN {type_labels})
              AND elem.enabled = true
            WITH elem
            WHERE NOT EXISTS {{
                MATCH (elem)-[r]-(connected)
                WHERE any(lbl IN labels(connected) WHERE lbl IN {connected_labels})
                  AND type(r) STARTS WITH '{ns}:'
            }}
            RETURN elem.identifier as identifier,
                   elem.name as name,
                   [lbl IN labels(elem) WHERE lbl <> '{ns}'][0] as label
        """

        floating = archimate_manager.query(query)

        if floating:
            logger.info(f"Found {len(floating)} {layer} elements not connected to {connected_to}")

            for elem in floating:
                element_type = elem["label"] if elem["label"] else "Unknown"
                result.issues_found += 1
                result.details.append(
                    {
                        "action": "flagged",
                        "identifier": elem["identifier"],
                        "name": elem["name"],
                        "element_type": element_type,
                        "layer": layer,
                        "not_connected_to": connected_to,
                        "reason": f"floating_{layer.lower()}_element",
                    }
                )
