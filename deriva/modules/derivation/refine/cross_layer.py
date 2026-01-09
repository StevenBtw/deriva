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
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

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
            graph_manager: Not used for this step
            llm_query_fn: Not used for this step
            params: Optional parameters:
                - check_business_to_app: Validate Business→App connections (default: True)
                - check_app_to_tech: Validate App→Tech connections (default: True)
                - strict_mode: Fail on any violations (default: False)

        Returns:
            RefineResult with details of cross-layer issues found
        """
        params = params or {}
        check_business_to_app = params.get("check_business_to_app", True)
        check_app_to_tech = params.get("check_app_to_tech", True)

        result = RefineResult(
            success=True,
            step_name="cross_layer_coherence",
        )

        try:
            ns = archimate_manager.namespace

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

            logger.info(
                f"Cross-layer coherence check complete: {result.issues_found} issues found"
            )

        except Exception as e:
            logger.exception(f"Error in cross-layer coherence check: {e}")
            result.success = False
            result.errors.append(str(e))

        return result

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
                   [lbl IN labels(source) WHERE lbl STARTS WITH '{ns}:'][0] as label
        """

        disconnected = archimate_manager.query(query)

        if disconnected:
            logger.info(
                f"Found {len(disconnected)} {source_layer} elements without "
                f"{target_layer} connections"
            )

            for elem in disconnected:
                element_type = elem["label"].split(":")[-1] if elem["label"] else "Unknown"
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
                   [lbl IN labels(elem) WHERE lbl STARTS WITH '{ns}:'][0] as label
        """

        floating = archimate_manager.query(query)

        if floating:
            logger.info(
                f"Found {len(floating)} {layer} elements not connected to {connected_to}"
            )

            for elem in floating:
                element_type = elem["label"].split(":")[-1] if elem["label"] else "Unknown"
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
