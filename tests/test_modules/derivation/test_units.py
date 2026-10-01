"""Components at the deployable-unit level (element config params.deployable_units).

When a repository has several units (directories holding a build or container file), the outermost units
are the candidates; a repository with fewer keeps its candidates.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from deriva.modules.derivation.base import Candidate, ElementPrompt, UnitFilter
from deriva.modules.derivation.element_base import ElementDerivationBase

TEST_PROMPT = ElementPrompt(persona="Derive elements.", candidates="Candidates.", rules="{abstention}Rules.", abstention="")
UNITS = UnitFilter(file_names=frozenset({"pom.xml", "build.gradle", "package.json"}), min_units=2)


def _dir(path: str) -> Candidate:
    return Candidate(node_id=f"dir::r::{path.replace('/', '_')}", name=path.rsplit("/", 1)[-1], labels=["Graph", "Directory"], properties={"path": f"r/{path}"})


class Derivation(ElementDerivationBase):
    ELEMENT_TYPE = "TestElement"
    OUTBOUND_RULES = []
    INBOUND_RULES = []

    def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
        return candidates[:max_candidates]


def _generate(candidates, build_files, units=UNITS):
    """``build_files``: directory path -> the file names it holds directly."""

    def query(cypher, params=None):
        if "fileName" in cypher and "IN $ids" in cypher:
            ids = set((params or {}).get("ids", []))
            names = {n.lower() for n in (params or {}).get("names", [])}
            return [{"id": c.node_id} for c in candidates if c.node_id in ids and {f.lower() for f in build_files.get(c.properties["path"], [])} & names]
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
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
            prompt=TEST_PROMPT,
            deployable_units=units,
        )


GATEWAY, GATEWAY_SECURITY, ENGINE, ENGINE_ACTORS, GUI = "gateway", "gateway/src/security", "engine", "engine/src/actors", "gui"


class TestDeployableUnits:
    CANDIDATES = [_dir(p) for p in (GATEWAY, GATEWAY_SECURITY, ENGINE, ENGINE_ACTORS, GUI)]

    def test_the_outermost_units_are_the_candidates(self):
        files = {f"r/{GATEWAY}": ["build.gradle"], f"r/{ENGINE}": ["pom.xml"], f"r/{GUI}": ["package.json"]}

        result = _generate(self.CANDIDATES, files)

        stages = {d.node_id.split("::")[-1]: d.stage for d in result.candidate_decisions}
        assert {stages[p.replace("/", "_")] for p in (GATEWAY, ENGINE, GUI)} == {"llm_rejected"}
        assert {stages[p.replace("/", "_")] for p in (GATEWAY_SECURITY, ENGINE_ACTORS)} == {"not_a_unit"}

    def test_a_unit_inside_another_unit_is_part_of_it(self):
        files = {f"r/{GATEWAY}": ["build.gradle"], f"r/{GATEWAY_SECURITY}": ["pom.xml"], f"r/{ENGINE}": ["pom.xml"]}

        result = _generate(self.CANDIDATES, files)

        stages = {d.node_id.split("::")[-1]: d.stage for d in result.candidate_decisions}
        assert stages[GATEWAY_SECURITY.replace("/", "_")] == "not_a_unit"
        assert {stages[GATEWAY], stages[ENGINE]} == {"llm_rejected"}

    def test_a_repository_with_fewer_units_keeps_its_candidates(self):
        result = _generate(self.CANDIDATES, {f"r/{GATEWAY}": ["build.gradle"]})

        assert {d.stage for d in result.candidate_decisions} == {"llm_rejected"}
        assert len(result.candidate_decisions) == len(self.CANDIDATES)

    def test_without_the_setting_nothing_changes(self):
        result = _generate(self.CANDIDATES, {f"r/{GATEWAY}": ["build.gradle"], f"r/{ENGINE}": ["pom.xml"]}, units=None)

        assert {d.stage for d in result.candidate_decisions} == {"llm_rejected"}
