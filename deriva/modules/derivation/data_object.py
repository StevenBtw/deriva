"""
DataObject Derivation.

A DataObject represents data structured for automated processing.
This includes database tables, files, messages, and other data structures.

Graph signals:
- File nodes (especially data files, configs, schemas)
- TypeDefinition nodes representing data structures
- Nodes related to persistence, storage, or data transfer

Filtering strategy:
1. Query File nodes with data-related types
2. Include schema/config/data files
3. Exclude source code and templates
4. Focus on structured data artifacts

LLM role:
- Identify which files/types represent data objects
- Generate meaningful data object names
- Write documentation describing the data purpose

Relationships:
- OUTBOUND: DataObject -> TechnologyService (Realization) - config realizes tech
- INBOUND: TechnologyService -> DataObject (Access) - tech accesses data
- INBOUND: ApplicationService -> DataObject (Access) - app services access data
- INBOUND: BusinessProcess -> DataObject (Access) - processes access data

ArchiMate Layer: Application Layer
ArchiMate Type: DataObject

Typical Sources:
    - File nodes with .json, .yaml, .xml, .csv extensions
    - Schema definition files and configuration files
"""

from __future__ import annotations

import logging

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class DataObjectDerivation(HybridDerivation):
    """
    DataObject element derivation.

    Uses hybrid filtering (patterns + graph metrics) to identify data files
    and structured data artifacts from File nodes.
    """

    ELEMENT_TYPE = "DataObject"
    MIN_PAGERANK = None  # Config files have low pagerank but are important for cross-layer connections
    USE_COMMUNITY_ROOTS = False  # Data files don't form communities

    OUTBOUND_RULES = []

    INBOUND_RULES = [
        RelationshipRule(
            target_type="TechnologyService",
            rel_type="Access",
            description="Technology services access data objects",
        ),
        RelationshipRule(
            target_type="ApplicationService",
            rel_type="Access",
            description="Application services access data objects",
        ),
        RelationshipRule(
            target_type="BusinessProcess",
            rel_type="Access",
            description="Business processes access data objects",
        ),
    ]

    # Uses HybridDerivation.filter_candidates() which handles:
    # - Pattern matching (include/exclude from config)
    # - Graph filtering (PageRank threshold, community roots)
