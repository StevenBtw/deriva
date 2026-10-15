"""roles.element_per "unit": one interface per deployable unit and channel, its endpoints as members."""

from __future__ import annotations

import json
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


def _file(path: str) -> Candidate:
    return Candidate(node_id=f"file::r::{path.replace('/', '_')}", name=path.rsplit("/", 1)[-1], labels=["Graph", "File"], properties={"path": path})


def _generate(candidates, answer):
    prompts: list[str] = []

    def llm(prompt, schema, **kwargs):
        prompts.append(prompt)
        items = [{"id": c.node_id, "role": answer[c.node_id]} for c in candidates if f'"{c.node_id}"' in prompt and c.node_id in answer]
        return SimpleNamespace(content=json.dumps({"items": items}))

    def query(cypher, params=None):
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
        [SimpleNamespace(name=name, identifier=f"ac_{i}", properties={"source": unit}) for i, (unit, (name, _, _)) in enumerate(UNITS.items())]
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
            roles=ROLES,
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


def test_a_candidate_that_no_unit_includes_is_left_out_with_its_reason():
    stray = _file("r/tools/report.py")

    result, _ = _generate([stray], {stray.node_id: "rest"})

    assert result.created_elements == []
    assert [d.stage for d in result.candidate_decisions] == ["no_unit"]
