"""Re-runnable extraction steps: which step owns a node or edge, and what a step run removes (mark and sweep).

Every node and edge an extraction step writes carries the step's name (``extractStep``; nodes also
``extractSteps``, the steps that produce them). When a step runs again it writes what it produces and
then removes what it wrote before and no longer produces: a node another step also produces only
loses this step from its list. Nodes produced again keep their identity, so the edges other steps
hang on them survive; a run with the same configuration leaves the graph as it was.

``node_step`` and ``edge_step`` give the owner of a node or edge written before steps were tagged
(the one-off ``graph tag-steps``), by its kind; what no rule covers is left untagged and never swept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Node kind -> the step that writes it (the steps that write one kind in two ways are decided below)
_NODE_STEPS = {
    "Repository": "Repository",
    "Directory": "Directory",
    "File": "File",
    "TypeDefinition": "TypeDefinition",  # Placeholders for unresolved base types come from it too
    "Method": "Method",
    "Test": "Test",
    "DeployableUnit": "DeployableUnit",
    "DataEntity": "DataEntity",
    "DataDomain": "DataDomain",
    "Lifecycle": "BusinessLayer",
    "LifecycleEvent": "BusinessLayer",
    "Role": "BusinessLayer",
    "Environment": "Deployment",
    "Deployment": "Deployment",
    "Software": "Deployment",
}

# (edge type, source kind, target kind) -> the step that writes it; None as a kind: any
_EDGE_STEPS: dict[tuple[str, str | None, str | None], str] = {
    ("CONTAINS", "Repository", "Directory"): "Directory",
    ("CONTAINS", "Directory", "Directory"): "Directory",
    ("CONTAINS", "Repository", "File"): "File",
    ("CONTAINS", "Directory", "File"): "File",
    ("CONTAINS", "File", "TypeDefinition"): "TypeDefinition",
    ("CONTAINS", "File", "Method"): "Method",
    ("CONTAINS", "TypeDefinition", "Method"): "Method",
    ("CONTAINS", "File", "Test"): "Test",
    ("INHERITS", None, None): "TypeDefinition",
    ("IMPORTS", None, None): "Imports",
    # USES: Imports writes it with the imported module, ExternalDependency (a declared dependency) without (edge_step)
    ("USES", None, None): "ExternalDependency",
    ("CALLS", None, None): "Calls",
    ("DECORATED_BY", None, None): "Decorators",
    ("REFERENCES", "Method", "TypeDefinition"): "References",
    ("REFERENCES", "File", "BusinessConcept"): "BusinessConcept",
    ("REPRESENTS", None, None): "DirectoryClassification",
    ("CONFIGURES", None, None): "Technology",
    ("INCLUDES", "DeployableUnit", None): "DeployableUnit",
    ("INCLUDES", "DataEntity", None): "DataEntity",
    ("NAMED_IN", "DataEntity", None): "DataEntity",
    ("INCLUDES", "DataDomain", None): "DataDomain",
    ("TRIGGERS", "Lifecycle", None): "BusinessLayer",
    ("TRIGGERS", "LifecycleEvent", None): "BusinessLayer",
    ("ASSIGNED", "Role", None): "BusinessLayer",
    ("RUNS", "Environment", None): "Deployment",
    ("DEPLOYS", "Deployment", None): "Deployment",
    ("HOSTS", "Environment", None): "Deployment",
    ("SERVES", "Software", None): "Deployment",
    ("CONSUMES", "DeployableUnit", None): "Cooperation",
    ("SENDS_TO", "DeployableUnit", None): "Cooperation",
}

IMPORT_STUB = "External package discovered via import"


def node_step(labels: list[str], properties: dict[str, Any]) -> str | None:
    """The step that writes a node, from its kind (and how it was made); None when no rule says."""
    kind = next((label for label in labels if label != "Graph"), "")
    method = str(properties.get("extractionMethod") or "")
    if kind in ("BusinessConcept", "Technology"):
        return "DirectoryClassification" if method == "llm-directory" else kind
    if kind == "ExternalDependency":
        return "Imports" if str(properties.get("description") or "").startswith(IMPORT_STUB) else "ExternalDependency"
    return _NODE_STEPS.get(kind)


def edge_step(edge_type: str, source_kind: str, target_kind: str, properties: dict[str, Any] | None = None) -> str | None:
    """The step that writes an edge, from its type, the kinds of its ends and (for USES) its properties; None when no rule says."""
    edge_type = edge_type.removeprefix("Graph:")
    if edge_type == "USES" and (properties or {}).get("module"):
        return "Imports"
    for (kind, source, target), step in _EDGE_STEPS.items():
        if kind == edge_type and source in (None, source_kind) and target in (None, target_kind):
            return step
    return None


@dataclass
class SweepPlan:
    """What a step run changes besides its writes: the step lists to set, the nodes and edges to remove."""

    set_steps: dict[str, list[str]] = field(default_factory=dict)
    delete_nodes: list[str] = field(default_factory=list)
    delete_edges: list[tuple[str, str, str]] = field(default_factory=list)


def plan_sweep(
    step: str,
    prior_nodes: dict[str, list[str]],
    produced_nodes: set[str],
    prior_edges: set[tuple[str, str, str]],
    produced_edges: set[tuple[str, str, str]],
) -> SweepPlan:
    """The sweep of one step run.

    Args:
        step: The step that ran
        prior_nodes: Node id -> the steps that produced it before the run (tagged nodes only)
        produced_nodes: The nodes the run wrote
        prior_edges: (source, type, target) of the edges this step wrote before the run
        produced_edges: The edges the run wrote
    """
    plan = SweepPlan()
    for node in sorted(produced_nodes):
        plan.set_steps[node] = sorted({*prior_nodes.get(node, []), step})
    for node, steps in sorted(prior_nodes.items()):
        if step not in steps or node in produced_nodes:
            continue
        rest = sorted(s for s in steps if s != step)
        if rest:
            plan.set_steps[node] = rest
        else:
            plan.delete_nodes.append(node)
    gone = set(plan.delete_nodes)
    plan.delete_edges = sorted(e for e in prior_edges - produced_edges if e[0] not in gone and e[2] not in gone)
    return plan
