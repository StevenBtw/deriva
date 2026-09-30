"""Candidates classified into a closed list of roles (element config params.roles): one element per chosen role."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from deriva.modules.derivation.base import Candidate, ElementPrompt, NamingConfig, RoleConfig, build_role_prompt, parse_role_answer
from deriva.modules.derivation.element_base import ElementDerivationBase

ROLES = RoleConfig(
    labels=frozenset({"Technology"}),
    instruction="ROLE INSTRUCTION",
    names={"alpha_server": "Alpha Server", "beta_server": "Beta Server"},
    documentation="Hosts {members}.",
    missing_retries=1,
)

TEST_PROMPT = ElementPrompt(persona="Derive elements.", candidates="Candidates.", rules="{abstention}Rules.", abstention="")


def _tech(node_id, name, category="platform"):
    return Candidate(node_id=node_id, name=name, labels=["Graph", "Technology"], properties={"techCategory": category})


class Derivation(ElementDerivationBase):
    ELEMENT_TYPE = "TestElement"
    OUTBOUND_RULES = []
    INBOUND_RULES = []

    def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
        return candidates[:max_candidates]


class TestDirectoryAlreadyAnElement:
    """One structural source, one element: a candidate whose directory is already an element's source is left out."""

    @staticmethod
    def _generate(candidates, represented, element_sources, skip_when_directory_is, max_candidates=10):
        """``represented``: directory id -> candidate id (REPRESENTS edges); ``element_sources``: sources of existing components."""

        def query(cypher, params=None):
            if "REPRESENTS" in cypher:
                return [{"dir": d, "id": c} for d, c in represented.items() if c in (params or {}).get("ids", [])]
            return []

        archimate_manager = MagicMock()
        archimate_manager.get_elements.side_effect = lambda element_type=None, enabled_only=False: [
            SimpleNamespace(name="Component", identifier=f"ac_{i}", properties={"source": s}) for i, s in enumerate(element_sources) if element_type == "ApplicationComponent"
        ]
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
        ):
            return Derivation().generate(
                graph_manager=MagicMock(query=MagicMock(side_effect=query)),
                archimate_manager=archimate_manager,
                llm_query_fn=MagicMock(return_value=SimpleNamespace(content='{"items": []}')),
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=max_candidates,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
                roles=ROLES,
                skip_when_directory_is=skip_when_directory_is,
            )

    CANDIDATES = [_tech("tech::r::gamma", "Gamma"), _tech("tech::r::delta", "Delta"), _tech("tech::r::epsilon", "Epsilon")]
    REPRESENTED = {"dir::r::gamma_module": "tech::r::gamma", "dir::r::delta_package": "tech::r::delta"}

    def test_a_candidate_whose_directory_is_a_component_is_left_out(self):
        result = self._generate(self.CANDIDATES, self.REPRESENTED, ["dir::r::gamma_module"], frozenset({"ApplicationComponent"}))

        stages = {d.node_id: d.stage for d in result.candidate_decisions}
        assert stages["tech::r::gamma"] == "filtered_out"
        assert stages["tech::r::delta"] != "filtered_out" and stages["tech::r::epsilon"] != "filtered_out"

    def test_without_the_param_every_candidate_stays(self):
        result = self._generate(self.CANDIDATES, self.REPRESENTED, ["dir::r::gamma_module"], None)

        assert "filtered_out" not in {d.stage for d in result.candidate_decisions}

    def test_a_represented_candidate_leaves_before_the_cut(self):
        # Two places: the represented candidate does not take one, so the next eligible candidate keeps its place
        result = self._generate(self.CANDIDATES, self.REPRESENTED, ["dir::r::gamma_module"], frozenset({"ApplicationComponent"}), max_candidates=2)

        stages = {d.node_id: d.stage for d in result.candidate_decisions}
        assert stages["tech::r::gamma"] == "filtered_out"
        assert stages["tech::r::delta"] != "filtered_out" and stages["tech::r::epsilon"] != "filtered_out"


class TestRolePrompt:
    def test_holds_the_instruction_the_roles_and_the_candidates(self):
        prompt = build_role_prompt([_tech("tech::r::gamma", "Gamma", "infrastructure")], ROLES.instruction, ROLES.names)

        assert "ROLE INSTRUCTION" in prompt
        assert "alpha_server" in prompt and "beta_server" in prompt and "none" in prompt
        assert '"id":"tech::r::gamma"' in prompt and '"name":"Gamma"' in prompt and '"category":"infrastructure"' in prompt

    def test_candidates_are_listed_in_the_order_given(self):
        prompt = build_role_prompt([_tech("b", "Beta"), _tech("a", "Alpha")], ROLES.instruction, ROLES.names)

        assert prompt.index('"id":"b"') < prompt.index('"id":"a"')

    def test_the_path_is_shown_only_when_asked(self):
        candidate = Candidate(node_id="file::r::a", name="A.java", labels=["Graph", "File"], properties={"path": "mod/src/A.java"})

        assert '"path"' not in build_role_prompt([candidate], ROLES.instruction, ROLES.names)
        assert '"path":"mod/src/A.java"' in build_role_prompt([candidate], ROLES.instruction, ROLES.names, show_path=True)


class TestParseRoleAnswer:
    def test_roles_and_none(self):
        content = '{"items": [{"id": "a", "role": "alpha_server"}, {"id": "b", "role": "none"}]}'

        assert parse_role_answer(content, {"a", "b"}, ROLES.names) == {"a": "alpha_server", "b": None}

    def test_unknown_ids_and_roles_are_left_out(self):
        content = '{"items": [{"id": "a", "role": "gamma_server"}, {"id": "x", "role": "alpha_server"}, {"id": "b", "role": "beta_server"}]}'

        assert parse_role_answer(content, {"a", "b"}, ROLES.names) == {"b": "beta_server"}

    def test_an_unreadable_answer_decides_nothing(self):
        assert parse_role_answer("not json", {"a"}, ROLES.names) == {}


class TestRoleElements:
    """Candidates with a role label are classified; each chosen role becomes one element."""

    @staticmethod
    def _generate(candidates, answers, naming_answers=(), roles=ROLES):
        """``answers``: per role call, the role per candidate id; the call answers the ids it was asked."""
        role_answers = iter(answers)
        names = iter(naming_answers)
        prompts: list[str] = []

        def llm(prompt, schema, **kwargs):
            prompts.append(prompt)
            if schema.get("name") == "role_classification":
                roles = next(role_answers)
                items = [{"id": c.node_id, "role": roles[c.node_id]} for c in candidates if f'"{c.node_id}"' in prompt and c.node_id in roles]
                return SimpleNamespace(content=json.dumps({"items": items}))
            if schema.get("name") == "element_naming":
                return SimpleNamespace(content=json.dumps({"name": next(names)}))
            sources = [c.node_id for c in candidates if f'"{c.node_id}"' in prompt]
            elements = [{"identifier": "x", "name": "n", "documentation": "d", "source": s, "confidence": 0.9} for s in sources]
            return SimpleNamespace(content=json.dumps({"elements": elements}))

        archimate_manager = MagicMock()
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
        ):
            result = Derivation().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=archimate_manager,
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
                naming=NamingConfig(instruction="NAMING RULES", samples=1),
                roles=roles,
            )
        return result, prompts

    def test_one_element_per_chosen_role(self):
        candidates = [_tech("tech::r::gamma", "Gamma"), _tech("tech::r::delta", "Delta"), _tech("tech::r::epsilon", "Epsilon")]
        answer = {"tech::r::gamma": "alpha_server", "tech::r::delta": "alpha_server", "tech::r::epsilon": "none"}

        result, prompts = self._generate(candidates, [answer])

        (element,) = result.created_elements
        assert (element["identifier"], element["name"]) == ("te_alpha_server", "Alpha Server")
        # The source is the first candidate by id (graph grounding); every member is recorded
        assert element["properties"]["source"] == "tech::r::delta"
        assert element["properties"]["sources"] == ["tech::r::delta", "tech::r::gamma"]
        assert element["properties"]["role"] == "alpha_server"
        assert element["documentation"] == "Hosts Delta, Gamma."
        assert len(prompts) == 1  # one role call, no keep or naming call for role candidates

    def test_decisions_name_the_role_element(self):
        candidates = [_tech("tech::r::gamma", "Gamma"), _tech("tech::r::epsilon", "Epsilon")]

        result, _ = self._generate(candidates, [{"tech::r::gamma": "beta_server", "tech::r::epsilon": "none"}])

        decisions = {d.node_id: (d.stage, d.element_id) for d in result.candidate_decisions}
        assert decisions == {"tech::r::gamma": ("created", "te_beta_server"), "tech::r::epsilon": ("llm_rejected", None)}

    def test_candidates_left_out_of_an_answer_are_asked_again(self):
        candidates = [_tech("tech::r::gamma", "Gamma"), _tech("tech::r::delta", "Delta")]

        result, prompts = self._generate(candidates, [{"tech::r::gamma": "alpha_server"}, {"tech::r::delta": "beta_server"}])

        assert [e["name"] for e in result.created_elements] == ["Alpha Server", "Beta Server"]
        assert '"tech::r::gamma"' not in prompts[1]  # the retry asks only the missing candidate

    def test_a_candidate_never_answered_is_recorded_as_unanswered(self):
        result, _ = self._generate([_tech("tech::r::gamma", "Gamma")], [{}, {}])

        assert result.created_elements == []
        assert [(d.stage, d.element_id) for d in result.candidate_decisions] == [("llm_unanswered", None)]

    def test_one_element_per_candidate_when_configured(self):
        """With element_per 'candidate' every candidate with a role is its own element; its kind is stored."""
        from dataclasses import replace

        candidates = [_tech("tech::r::gamma", "GammaDB"), _tech("tech::r::delta", "Delta"), _tech("tech::r::epsilon", "Epsilon")]
        answer = {"tech::r::gamma": "alpha_server", "tech::r::delta": "alpha_server", "tech::r::epsilon": "none"}

        result, prompts = self._generate(candidates, [answer], roles=replace(ROLES, element_per="candidate", documentation="{role} ({members})"))

        elements = {e["identifier"]: e for e in result.created_elements}
        assert set(elements) == {"te_gamma", "te_delta"}
        # The name is the candidate's own name as written (no word splitting of product names)
        assert (elements["te_gamma"]["name"], elements["te_gamma"]["properties"]["role"]) == ("GammaDB", "alpha_server")
        assert elements["te_gamma"]["properties"]["source"] == "tech::r::gamma"
        assert elements["te_gamma"]["documentation"] == "Alpha Server (GammaDB)"
        assert len(prompts) == 1  # no naming call
        decisions = {d.node_id: (d.stage, d.element_id) for d in result.candidate_decisions}
        assert decisions["tech::r::epsilon"] == ("llm_rejected", None)
        assert decisions["tech::r::gamma"] == ("created", "te_gamma")

    def test_other_candidates_keep_the_keep_and_naming_path_without_taking_a_role_name(self):
        candidates = [_tech("tech::r::gamma", "Gamma"), Candidate(node_id="file::r::zeta", name="zeta.cfg", labels=["Graph", "File"], properties={})]

        result, _ = self._generate(candidates, [{"tech::r::gamma": "alpha_server"}], naming_answers=["Alpha Server"])

        assert {e["properties"]["source"]: e["name"] for e in result.created_elements} == {"tech::r::gamma": "Alpha Server", "file::r::zeta": "Zeta"}


class TestRoleNameTemplate:
    """With a name template, each candidate with a role is named container + subject + role, from structure."""

    ROLES = RoleConfig(
        labels=frozenset({"File"}),
        instruction="KIND INSTRUCTION",
        names={"http": "HTTP API", "cli": "CLI"},
        documentation="{role} of {container}: {subject}.",
        element_per="candidate",
        name_template="{container} {subject} {role}",
        container_type="ApplicationComponent",
        show_path=True,
    )

    @staticmethod
    def _file(name, path):
        return Candidate(node_id=f"file::r::{path.replace('/', '_')}", name=name, labels=["Graph", "File"], properties={"path": path})

    @classmethod
    def _generate(cls, candidates, answer, containers, decisions=None):
        """``containers``: (directory id, directory path, element name) of the container elements; ``decisions`` collects the stage per candidate."""
        prompts: list[str] = []

        def llm(prompt, schema, **kwargs):
            prompts.append(prompt)
            items = [{"id": c.node_id, "role": answer[c.node_id]} for c in candidates if f'"{c.node_id}"' in prompt and c.node_id in answer]
            return SimpleNamespace(content=json.dumps({"items": items}))

        def query(cypher, params=None):
            if "Graph:Directory" in cypher:
                ids = set((params or {}).get("ids", []))
                return [{"id": d, "path": p} for d, p, _ in containers if d in ids]
            return []

        archimate_manager = MagicMock()
        archimate_manager.get_elements.side_effect = lambda element_type=None, enabled_only=False: (
            [SimpleNamespace(name=n, identifier=f"ac_{i}", properties={"source": d}) for i, (d, _, n) in enumerate(containers)] if element_type == "ApplicationComponent" else []
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
                roles=cls.ROLES,
            )
        if decisions is not None:
            decisions.update({d.node_id: d.stage for d in result.candidate_decisions})
        return {e["properties"]["source"]: e for e in result.created_elements}, prompts

    def test_the_name_is_container_subject_and_role(self):
        widget = self._file("WidgetController.java", "shop/src/WidgetController.java")

        elements, prompts = self._generate([widget], {widget.node_id: "http"}, [("dir::r::shop", "shop", "Shop")])

        element = elements[widget.node_id]
        assert element["name"] == "Shop Widget HTTP API"
        assert element["documentation"] == "HTTP API of Shop: Widget."
        assert element["properties"]["role"] == "http"
        assert len(prompts) == 1  # one classification call, no naming call

    def test_each_word_appears_once(self):
        store = self._file("WidgetStoreController.java", "store/src/WidgetStoreController.java")
        tool = self._file("Cli.java", "store/bin/Cli.java")

        elements, _ = self._generate([store, tool], {store.node_id: "http", tool.node_id: "cli"}, [("dir::r::store", "store", "Widget Store")])

        assert elements[store.node_id]["name"] == "Widget Store HTTP API"
        assert elements[tool.node_id]["name"] == "Widget Store Cli"

    def test_a_planned_name_given_before_leaves_the_candidate_out(self):
        # Different structure names, one planned name: "Shop" + "Shop Widget" and "Shop" + "Widget"
        first = self._file("ShopWidgetController.java", "shop/src/a/ShopWidgetController.java")
        second = self._file("WidgetController.java", "shop/src/b/WidgetController.java")
        decisions: dict[str, str] = {}

        elements, _ = self._generate([first, second], {first.node_id: "http", second.node_id: "http"}, [("dir::r::shop", "shop", "Shop")], decisions)

        assert [e["name"] for e in elements.values()] == ["Shop Widget HTTP API"]
        assert decisions[first.node_id] == "created"
        assert decisions[second.node_id] == "duplicate_removed"

    def test_the_nearest_container_names_it(self):
        admin = self._file("PanelController.java", "shop/admin/PanelController.java")

        elements, _ = self._generate([admin], {admin.node_id: "http"}, [("dir::r::shop", "shop", "Shop"), ("dir::r::shop_admin", "shop/admin", "Shop Admin")])

        assert elements[admin.node_id]["name"] == "Shop Admin Panel HTTP API"

    def test_without_a_container_the_top_level_module_names_it(self):
        tool = self._file("Cli.java", "gadget-tools/src/Cli.java")

        elements, _ = self._generate([tool], {tool.node_id: "cli"}, [("dir::r::shop", "shop", "Shop")])

        assert elements[tool.node_id]["name"] == "Gadget Tools Cli"

    def test_none_makes_no_element_and_the_prompt_holds_structure_only(self):
        client = self._file("WidgetClient.java", "shop/src/WidgetClient.java")

        elements, prompts = self._generate([client], {client.node_id: "none"}, [("dir::r::shop", "shop", "Shop")])

        assert elements == {}
        assert '"path":"shop/src/WidgetClient.java"' in prompts[0]
        # The container's name can be an LLM-written element name: it never goes into a prompt
        assert "Shop" not in prompts[0]


class TestRoleNamingCall:
    """With naming_call, each element of the role path starts from its structure name and the step's naming call may rename it."""

    ROLES = RoleConfig(
        labels=frozenset({"BusinessConcept"}),
        instruction="KIND INSTRUCTION",
        names={"kind": "Kind"},
        element_per="candidate",
        name_template="{subject}",
        naming_call=True,
    )

    @staticmethod
    def _concept(node_id, name):
        return Candidate(node_id=node_id, name=name, labels=["Graph", "BusinessConcept"], properties={"confidence": 0.9})

    @classmethod
    def _generate(cls, candidates, kinds, names):
        """``kinds``: the role per candidate id; ``names``: the naming answer per candidate name (None: no usable answer)."""
        prompts: list[str] = []

        def llm(prompt, schema, **kwargs):
            prompts.append(prompt)
            if schema.get("name") == "role_classification":
                items = [{"id": c.node_id, "role": kinds[c.node_id]} for c in candidates if f'"{c.node_id}"' in prompt]
                return SimpleNamespace(content=json.dumps({"items": items}))
            (candidate,) = [c for c in candidates if f'"name":"{c.name}"' in prompt]
            return SimpleNamespace(content=json.dumps({"name": names[candidate.name]}))

        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
        ):
            result = Derivation().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=MagicMock(get_elements=MagicMock(return_value=[])),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
                naming=NamingConfig(instruction="NAMING GUIDE", samples=1),
                roles=cls.ROLES,
            )
        return {e["properties"]["source"]: e for e in result.created_elements}, prompts

    def test_the_naming_call_renames_the_element(self):
        alpha = self._concept("concept::r::alpha", "Alpha")

        elements, prompts = self._generate([alpha], {alpha.node_id: "kind"}, {"Alpha": "Alpha Handling"})

        element = elements[alpha.node_id]
        assert element["name"] == "Alpha Handling"
        assert element["properties"]["structure_name"] == "Alpha"
        assert len(prompts) == 2  # one classification call, one naming call
        assert "NAMING GUIDE" in prompts[1]

    def test_no_naming_call_for_candidates_without_a_role(self):
        alpha, beta = self._concept("concept::r::alpha", "Alpha"), self._concept("concept::r::beta", "Beta")

        elements, prompts = self._generate([alpha, beta], {alpha.node_id: "kind", beta.node_id: "none"}, {"Alpha": "Alpha Handling", "Beta": "Beta Handling"})

        assert list(elements) == [alpha.node_id]
        assert len(prompts) == 2

    def test_a_name_another_element_already_has_keeps_the_structure_name(self):
        alpha, beta = self._concept("concept::r::alpha", "Alpha"), self._concept("concept::r::beta", "Beta")

        elements, _ = self._generate([alpha, beta], {alpha.node_id: "kind", beta.node_id: "kind"}, {"Alpha": "Shared Name", "Beta": "Shared Name"})

        assert (elements[alpha.node_id]["name"], elements[beta.node_id]["name"]) == ("Shared Name", "Beta")

    def test_without_a_usable_answer_the_structure_name_stays(self):
        alpha = self._concept("concept::r::alpha", "Alpha")

        elements, _ = self._generate([alpha], {alpha.node_id: "kind"}, {"Alpha": None})

        assert elements[alpha.node_id]["name"] == "Alpha"
