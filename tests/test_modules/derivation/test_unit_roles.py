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


def _generate(candidates, answer, roles=ROLES, web_entries=None, sources=None, methods=None, enrichments=None, on_candidates=None, derivation=None):
    """``sources``: path -> text of the units' source files (read through ``source_text``); ``methods``: path -> names it defines."""
    prompts: list[str] = []

    def llm(prompt, schema, **kwargs):
        prompts.append(prompt)
        items = [{"id": c.node_id, "role": answer[c.node_id]} for c in candidates if f'"{c.node_id}"' in prompt and c.node_id in answer]
        return SimpleNamespace(content=json.dumps({"items": items}))

    def query(cypher, params=None):
        if "fileType" in cypher:
            return [{"node": f"file::r::{path.replace('/', '_')}", "path": path} for path in sorted(sources or {})]
        if "Graph:Method" in cypher:
            assert params is not None
            return [{"path": path, "name": name} for path in sorted(params["paths"]) for name in (methods or {}).get(path, [])]
        if "webEntries" in cypher:
            return [{"unit": unit, "node": f"file::r::{path.replace('/', '_')}", "path": path} for unit, paths in sorted((web_entries or {}).items()) for path in paths]
        if "Graph:INCLUDES" in cypher:
            assert params is not None
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
        patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value=enrichments or {}),
        patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
    ):
        result = (derivation or Derivation)().generate(
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
            source_text=None if sources is None else sources.get,
            on_candidates=on_candidates,
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
    assert by_name["Shop Backend Web UI"]["members"] == [{"name": "home.html", "source": "file::r::r_shop_templates_home.html", "role": "web"}]
    assert len(prompts) == 1 and "home.html" not in prompts[0]  # only the endpoint file was asked


def test_an_interface_name_never_equals_its_components_name():
    """The word dedupe can swallow the channel word ("Ledger Online" + "Online"); then "Interface" goes at the end."""
    screen = Candidate(node_id="typedef::r::MAP1", name="MAP1", labels=["Graph", "TypeDefinition"], properties={"filePath": "r/app/bms/MAP1.bms", "category": "screen"})
    roles = replace(ROLES, names={**ROLES.names, "web": "Online"})

    result, _ = _generate([screen], {}, roles=roles)

    assert [e["name"] for e in result.created_elements] == ["Ledger Online Interface"]


def test_the_channel_merges_with_the_component_name_only_where_they_overlap():
    from deriva.modules.derivation.element_base import _merge_channel

    assert _merge_channel("Shop Batch", "Batch Jobs") == "Shop Batch Jobs"
    assert _merge_channel("Shop UI", "Web UI") == "Shop UI Web UI"  # "UI" is no overlap of "Web UI"
    assert _merge_channel("WebUI", "Web UI") == "WebUI Interface"  # the whole channel is in the name already
    assert _merge_channel("Order Batch Jobs", "Batch Jobs") == "Order Batch Jobs Interface"
    assert _merge_channel("Deriva CLI", "Commands") == "Deriva CLI Commands"


def test_a_file_two_units_include_is_documented_with_each_units_component(monkeypatch):
    monkeypatch.setitem(UNITS, "unit::r::admin", ("Admin Backend", {"r/shop/orders.py"}, set()))
    orders = _file("r/shop/orders.py")

    result, _ = _generate([orders], {orders.node_id: "rest"})

    documentation = {e["name"]: e["documentation"] for e in result.created_elements}
    assert documentation == {"Admin Backend REST API": "REST API of Admin Backend: orders.py.", "Shop Backend REST API": "REST API of Shop Backend: orders.py."}


def test_one_interface_per_unit_is_named_after_the_role_with_the_most_members_and_lists_the_others():
    """roles.one_per_unit: the unit's channels merge into one interface; the role most members have names it."""
    orders, users = _file("r/shop/orders.py"), _file("r/shop/users.py")
    roles = replace(ROLES, unit_roles=(("webEntries", "web"),), one_per_unit=True)
    pages = {"unit::r::shop": ["r/shop/templates/home.html"]}

    result, _ = _generate([orders, users], {orders.node_id: "rest", users.node_id: "rest"}, roles=roles, web_entries=pages)

    (interface,) = result.created_elements
    assert interface["name"] == "Shop Backend REST API" and interface["identifier"].endswith("_shop__rest")
    assert interface["properties"]["role"] == "rest" and interface["properties"]["roles"] == ["rest", "web"]
    assert [m["name"] for m in interface["properties"]["members"]] == ["orders.py", "home.html", "users.py"]  # in node id order


def test_a_tie_between_roles_goes_to_the_first_role_in_the_configured_order():
    orders = _file("r/shop/orders.py")
    roles = replace(ROLES, unit_roles=(("webEntries", "web"),), one_per_unit=True)

    result, _ = _generate([orders], {orders.node_id: "rest"}, roles=roles, web_entries={"unit::r::shop": ["r/shop/templates/home.html"]})

    (interface,) = result.created_elements
    assert interface["properties"]["role"] == "rest"  # one member each: rest comes before web in names


def test_each_member_of_a_merged_interface_keeps_its_own_role():
    """The channel a member was classified into stays on the member, so later steps read the member's role."""
    orders = _file("r/shop/orders.py")
    roles = replace(ROLES, unit_roles=(("webEntries", "web"),), one_per_unit=True)

    result, _ = _generate([orders], {orders.node_id: "rest"}, roles=roles, web_entries={"unit::r::shop": ["r/shop/templates/home.html"]})

    (interface,) = result.created_elements
    assert {m["name"]: m["role"] for m in interface["properties"]["members"]} == {"orders.py": "rest", "home.html": "web"}


# A registration call names the service it serves; generated code defines the same function
REGISTRATION = replace(
    ROLES,
    names={**ROLES.names, "rpc": "RPC API"},
    registration_role="rpc",
    registrations=(r"\bRegister(?P<service>\w+?)Server\s*\(",),
    excluded_services=("Health",),
)
CART = ("Cart Backend", {"r/cart/main.go", "r/cart/genproto/demo_grpc.pb.go"}, set())
MAIN = "func main() {\n\tpb.RegisterCartServiceServer(srv, svc)\n\thealthpb.RegisterHealthServer(srv, check)\n}\n"
GENERATED = "func RegisterCartServiceServer(s grpc.ServiceRegistrar, srv CartServiceServer) {\n}\n"


def test_a_file_that_calls_a_registration_is_an_rpc_interface_without_an_llm_call(monkeypatch):
    """Structure decides (roles.registrations): the call names the service, the unit names the interface."""
    monkeypatch.setitem(UNITS, "unit::r::cart", CART)

    result, prompts = _generate([], {}, roles=REGISTRATION, sources={"r/cart/main.go": MAIN})

    (interface,) = result.created_elements
    assert interface["name"] == "Cart Backend RPC API" and interface["properties"]["role"] == "rpc"
    assert interface["properties"]["source"] == "unit::r::cart"
    # The member is named after the service it registers, as written (not after its file)
    assert interface["properties"]["members"] == [{"name": "CartService", "source": "file::r::r_cart_main.go", "role": "rpc", "as_written": True}]
    assert prompts == []


def test_generated_code_that_defines_the_registration_is_no_interface(monkeypatch):
    """Only a call counts: a match whose first name is a method the file defines is that definition."""
    monkeypatch.setitem(UNITS, "unit::r::cart", CART)
    sources = {"r/cart/genproto/demo_grpc.pb.go": GENERATED}

    result, _ = _generate([], {}, roles=REGISTRATION, sources=sources, methods={"r/cart/genproto/demo_grpc.pb.go": ["RegisterCartServiceServer"]})

    assert result.created_elements == []


def test_a_technical_service_alone_makes_no_interface(monkeypatch):
    """excluded_services (in full, ignoring case): a health check is no access point of the product."""
    monkeypatch.setitem(UNITS, "unit::r::cart", CART)

    result, _ = _generate([], {}, roles=REGISTRATION, sources={"r/cart/main.go": "healthpb.RegisterHealthServer(srv, check)\n"})

    assert result.created_elements == []


def test_a_registered_file_the_query_also_found_is_not_asked(monkeypatch):
    monkeypatch.setitem(UNITS, "unit::r::cart", CART)
    main = _file("r/cart/main.go")
    orders = _file("r/shop/orders.py")

    result, prompts = _generate([main, orders], {orders.node_id: "rest", main.node_id: "rest"}, roles=REGISTRATION, sources={"r/cart/main.go": MAIN})

    by_name = {e["name"]: e["properties"] for e in result.created_elements}
    assert sorted(by_name) == ["Cart Backend RPC API", "Shop Backend REST API"]
    assert [m["name"] for m in by_name["Cart Backend RPC API"]["members"]] == ["CartService"]
    assert len(prompts) == 1 and "main.go" not in prompts[0]


def test_without_registrations_a_registration_call_makes_no_interface(monkeypatch):
    monkeypatch.setitem(UNITS, "unit::r::cart", CART)

    result, _ = _generate([], {}, roles=ROLES, sources={"r/cart/main.go": MAIN})

    assert result.created_elements == []


class _DropsFiles(Derivation):
    """A step whose filter drops every file candidate (a registered file the query found is filtered out)."""

    def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
        return [c for c in candidates if "File" not in c.labels][:max_candidates]


def test_a_registered_file_is_decided_once_with_its_graph_enrichment_and_reported_as_a_candidate(monkeypatch):
    """Structure decides a registered file: a filter stage that dropped it leaves no decision of its own, the decision
    and the candidate carry the file's graph measures, and the step reports the file among its candidates."""
    monkeypatch.setitem(UNITS, "unit::r::cart", CART)
    main = _file("r/cart/main.go")
    reported: list[list[str]] = []
    enrichments = {main.node_id: {"pagerank": 0.25, "louvain_community": "7", "in_degree": 3}}

    result, _ = _generate([main], {}, roles=REGISTRATION, sources={"r/cart/main.go": MAIN}, enrichments=enrichments, on_candidates=reported.append, derivation=_DropsFiles)

    decisions = [d for d in result.candidate_decisions if d.node_id == main.node_id]
    assert len(decisions) == 1 and decisions[0].became_element
    assert (decisions[0].pagerank, decisions[0].in_degree) == (0.25, 3)
    assert reported == [[main.node_id]]
