"""roles.element_per "unit": one interface per deployable unit and channel, its endpoints as members."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from deriva.modules.derivation.base import Candidate, RoleConfig
from tests.test_modules.derivation.test_roles import TEST_PROMPT, Derivation

ROLES = RoleConfig(
    labels=frozenset({"File", "TypeDefinition"}),
    instruction="CHANNELS",
    names={"rest": "REST API", "web": "Web UI", "batch": "Batch"},
    documentation="{role} of {container}: {members}.",
    element_per="unit",
    name_template="{container} {role}",
    container_type="ApplicationComponent",
    structural=(("category", "^screen$", "web"),),
)
# unit id -> (component name, member file paths, member node ids)
UNITS = {
    "unit::r::shop": ("Shop Backend", {"r/shop/orders.py", "r/shop/users.py"}, set()),
    "unit::r::app::online": ("Ledger Online", {"r/app/bms/MAP1.bms"}, {"typedef::r::MAP1"}),
}
# unit id -> the component's structure name (the fallback of its naming call); none for the online unit
STRUCTURE = {"unit::r::shop": "Shop"}


def _file(path: str) -> Candidate:
    return Candidate(node_id=f"file::r::{path.replace('/', '_')}", name=path.rsplit("/", 1)[-1], labels=["Graph", "File"], properties={"path": path})


def _generate(candidates, answer, roles=ROLES, web_entries=None):
    prompts: list[str] = []

    def llm(prompt, schema, **kwargs):
        prompts.append(prompt)
        items = [{"id": c.node_id, "role": answer[c.node_id]} for c in candidates if f'"{c.node_id}"' in prompt and c.node_id in answer]
        return SimpleNamespace(content=json.dumps({"items": items}))

    def query(cypher, params=None):
        if "webEntries" in cypher:
            return [{"unit": unit, "node": f"file::r::{path.replace('/', '_')}", "path": path} for unit, paths in sorted((web_entries or {}).items()) for path in paths]
        if "Graph:INCLUDES" in cypher:
            ids, paths = set(params["ids"]), set(params["paths"])
            rows = []
            for unit, (_, files, nodes) in UNITS.items():
                rows += [{"unit": unit, "node": None, "path": p} for p in sorted(files & paths)]
                rows += [{"unit": unit, "node": n, "path": None} for n in sorted(nodes & ids)]
            return rows
        return []

    archimate_manager = MagicMock()
    archimate_manager.get_elements.side_effect = lambda element_type=None, enabled_only=False: (
        [
            SimpleNamespace(name=name, identifier=f"ac_{i}", properties={"source": unit, **({"structure_name": STRUCTURE[unit]} if unit in STRUCTURE else {})})
            for i, (unit, (name, _, _)) in enumerate(UNITS.items())
        ]
        if element_type == "ApplicationComponent"
        else []
    )
    with (
        patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
        patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
    ):
        result = Derivation().generate(
            graph_manager=MagicMock(query=MagicMock(side_effect=query)),
            archimate_manager=archimate_manager,
            llm_query_fn=llm,
            query="MATCH (n) RETURN n",
            instruction="Test",
            example="{}",
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
            prompt=TEST_PROMPT,
            roles=roles,
        )
    return result, prompts


def test_the_endpoints_of_one_unit_and_channel_become_one_interface_with_them_as_members():
    orders, users = _file("r/shop/orders.py"), _file("r/shop/users.py")
    screen = Candidate(node_id="typedef::r::MAP1", name="MAP1", labels=["Graph", "TypeDefinition"], properties={"filePath": "r/app/bms/MAP1.bms", "category": "screen"})

    result, prompts = _generate([orders, users, screen], {orders.node_id: "rest", users.node_id: "rest"})

    by_name = {e["name"]: e for e in result.created_elements}
    assert sorted(by_name) == ["Ledger Online Web UI", "Shop Backend REST API"]
    rest = by_name["Shop Backend REST API"]
    assert rest["identifier"].endswith("_shop__rest")  # identity from the unit and the channel
    assert rest["properties"]["source"] == "unit::r::shop" and rest["properties"]["role"] == "rest"
    assert [m["name"] for m in rest["properties"]["members"]] == ["orders.py", "users.py"]
    assert rest["documentation"] == "REST API of Shop Backend: orders.py, users.py."
    # The screen's channel comes from structure: only the two files were asked
    assert len(prompts) == 1 and "MAP1" not in prompts[0]


def test_an_interface_carries_a_structure_name_from_its_components_structure_name():
    """Name matching may only read structure (rule 6d): the template filled with the component's structure name."""
    orders = _file("r/shop/orders.py")
    screen = Candidate(node_id="typedef::r::MAP1", name="MAP1", labels=["Graph", "TypeDefinition"], properties={"filePath": "r/app/bms/MAP1.bms", "category": "screen"})

    result, _ = _generate([orders, screen], {orders.node_id: "rest"})

    by_name = {e["name"]: e["properties"] for e in result.created_elements}
    assert by_name["Shop Backend REST API"]["structure_name"] == "Shop REST API"
    assert by_name["Ledger Online Web UI"]["structure_name"] == "Ledger Online Web UI"  # no structure name: the component's name


def test_a_candidate_that_no_unit_includes_is_left_out_with_its_reason():
    stray = _file("r/tools/report.py")

    result, _ = _generate([stray], {stray.node_id: "rest"})

    assert result.created_elements == []
    assert [d.stage for d in result.candidate_decisions] == ["no_unit"]


def test_a_unit_with_web_entries_gets_a_web_ui_from_structure_without_an_llm_call():
    """Server-rendered pages and page entries are a Web UI, decided by structure (roles.unit_roles)."""
    orders = _file("r/shop/orders.py")
    roles = replace(ROLES, unit_roles=(("webEntries", "web"),))

    result, prompts = _generate([orders], {orders.node_id: "rest"}, roles=roles, web_entries={"unit::r::shop": ["r/shop/templates/home.html"]})

    by_name = {e["name"]: e["properties"] for e in result.created_elements}
    assert sorted(by_name) == ["Shop Backend REST API", "Shop Backend Web UI"]
    assert by_name["Shop Backend Web UI"]["members"] == [{"name": "home.html", "source": "file::r::r_shop_templates_home.html"}]
    assert len(prompts) == 1 and "home.html" not in prompts[0]  # only the endpoint file was asked


def test_an_interface_name_never_equals_its_components_name():
    """The word dedupe can swallow the channel word ("Ledger Online" + "Online"); then "Interface" goes at the end."""
    screen = Candidate(node_id="typedef::r::MAP1", name="MAP1", labels=["Graph", "TypeDefinition"], properties={"filePath": "r/app/bms/MAP1.bms", "category": "screen"})
    roles = replace(ROLES, names={**ROLES.names, "web": "Online"})

    result, _ = _generate([screen], {}, roles=roles)

    assert [e["name"] for e in result.created_elements] == ["Ledger Online Interface"]


def test_the_channel_merges_with_the_component_name_only_where_they_overlap():
    from deriva.modules.derivation.element_base import _merge_channel

    assert _merge_channel("CardDemo Batch", "Batch Jobs") == "CardDemo Batch Jobs"
    assert _merge_channel("TeaStore UI", "Web UI") == "TeaStore UI Web UI"  # "UI" is no overlap of "Web UI"
    assert _merge_channel("WebUI", "Web UI") == "WebUI Interface"  # the whole channel is in the name already
    assert _merge_channel("Order Batch Jobs", "Batch Jobs") == "Order Batch Jobs Interface"
    assert _merge_channel("Deriva CLI", "Commands") == "Deriva CLI Commands"
