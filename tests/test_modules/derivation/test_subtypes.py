"""One element per contract (element config params.skip_subtypes): a type that inherits from another candidate type of the repository is represented by it."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deriva.modules.derivation.base import Candidate, ElementPrompt
from deriva.modules.derivation.element_base import ElementDerivationBase

TEST_PROMPT = ElementPrompt(persona="Derive elements.", candidates="Candidates.", rules="{abstention}Rules.", abstention="")

SHAPE = "typedef::r::Shape.java::Shape"
CIRCLE = "typedef::r::Circle.java::Circle"
SQUARE = "typedef::r::Square.java::Square"
RENDERER = "typedef::r::Renderer.java::Renderer"


def _type(node_id: str) -> Candidate:
    return Candidate(node_id=node_id, name=node_id.rsplit("::", 1)[1], labels=["Graph", "TypeDefinition"], properties={"category": "class"})


class Derivation(ElementDerivationBase):
    ELEMENT_TYPE = "TestElement"
    OUTBOUND_RULES = []
    INBOUND_RULES = []

    def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
        return candidates[:max_candidates]


class TestSubtypesLeaveTheList:
    CANDIDATES = [_type(SHAPE), _type(CIRCLE), _type(SQUARE), _type(RENDERER)]
    INHERITS = [(CIRCLE, SHAPE), (SQUARE, SHAPE)]

    @staticmethod
    def _generate(candidates, inherits, skip_subtypes, max_candidates=10):
        """``inherits``: (subtype id, base id) pairs of inheritance edges to types defined in the repository."""

        def query(cypher, params=None):
            if "INHERITS" in cypher:
                ids = set((params or {}).get("ids", []))
                return [{"id": sub} for sub, base in inherits if sub in ids and base in ids]
            return []

        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=list(candidates)),
        ):
            return Derivation().generate(
                graph_manager=MagicMock(query=MagicMock(side_effect=query)),
                archimate_manager=MagicMock(get_elements=MagicMock(return_value=[])),
                llm_query_fn=MagicMock(return_value=SimpleNamespace(content='{"elements": []}')),
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=max_candidates,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
                skip_subtypes=skip_subtypes,
            )

    def test_a_subtype_of_another_candidate_is_left_out(self):
        result = self._generate(self.CANDIDATES, self.INHERITS, skip_subtypes=True)

        stages = {d.node_id: d.stage for d in result.candidate_decisions}
        assert stages[CIRCLE] == stages[SQUARE] == "duplicate_removed"
        assert stages[SHAPE] != "duplicate_removed" and stages[RENDERER] != "duplicate_removed"

    def test_without_the_param_every_candidate_stays(self):
        result = self._generate(self.CANDIDATES, self.INHERITS, skip_subtypes=False)

        assert "duplicate_removed" not in {d.stage for d in result.candidate_decisions}

    def test_subtypes_leave_before_the_cut(self):
        # With two places, the two contracts take them: the subtypes never compete for a place
        result = self._generate(self.CANDIDATES, self.INHERITS, skip_subtypes=True, max_candidates=2)

        stages = {d.node_id: d.stage for d in result.candidate_decisions}
        assert stages[SHAPE] != "filtered_out" and stages[RENDERER] != "filtered_out"


class TestSubtypeQuery:
    """Only a base type defined in the repository represents a subtype, never an external placeholder."""

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def test_the_base_must_be_a_candidate_defined_in_the_repository(self, graph):
        from deriva.adapters.graph.models import TypeDefinitionNode

        def add(node_id, category):
            name = node_id.rsplit("::", 1)[1]
            graph.add_node(TypeDefinitionNode(name=name, type_category=category, file_path=f"r/{name}.java", repository_name="r"), node_id=node_id)

        placeholder = "typedef::r::Widget.java::ExternalBase"
        widget = "typedef::r::Widget.java::Widget"
        add(SHAPE, "other")
        add(CIRCLE, "class")
        add(RENDERER, "class")
        add(placeholder, "external_reference")
        add(widget, "class")
        graph.add_edge(src_id=CIRCLE, dst_id=SHAPE, relationship="INHERITS")
        graph.add_edge(src_id=widget, dst_id=placeholder, relationship="INHERITS")
        graph.add_edge(src_id=RENDERER, dst_id=SHAPE, relationship="INHERITS")

        candidates = [_type(node_id) for node_id in (SHAPE, CIRCLE, RENDERER, placeholder, widget)]

        # Widget's base is only a placeholder (an external type): Widget stays
        assert Derivation()._subtypes_of_candidates(candidates, graph) == {CIRCLE, RENDERER}
        # Without the base among the candidates its subtypes stay
        assert Derivation()._subtypes_of_candidates([c for c in candidates if c.node_id != SHAPE], graph) == set()
