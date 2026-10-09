"""One module, one element (element config params.skip_nested).

A selected directory that holds nearly all of its nearest selected ancestor's files of a type is represented by that ancestor.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deriva.modules.derivation.base import Candidate, ElementPrompt, NestedFilter
from deriva.modules.derivation.element_base import ElementDerivationBase

TEST_PROMPT = ElementPrompt(persona="Derive elements.", candidates="Candidates.", rules="{abstention}Rules.", abstention="")
SOURCE = NestedFilter(file_type="source", min_share=0.9)

GUI = "dir::r::gui"
GUI_SRC = "dir::r::gui_src"
CORE = "dir::r::core"
CORE_CRUD = "dir::r::core_crud"
UTIL = "dir::r::util"


def _dir(node_id: str) -> Candidate:
    return Candidate(node_id=node_id, name=node_id.rsplit("_", 1)[-1].rsplit("::", 1)[-1], labels=["Graph", "Directory"], properties={})


class Derivation(ElementDerivationBase):
    ELEMENT_TYPE = "TestElement"
    OUTBOUND_RULES = []
    INBOUND_RULES = []

    def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
        return candidates[:max_candidates]


class TestNestedDirectoriesLeaveTheList:
    @staticmethod
    def _generate(candidates, contains, files, skip_nested, max_candidates=10):
        """``contains``: (ancestor id, descendant id) pairs; ``files``: files of the type below each directory."""

        def query(cypher, params=None):
            ids = set((params or {}).get("ids", []))
            if "count(" in cypher:
                return [{"id": node_id, "n": n} for node_id, n in files.items() if node_id in ids and n]
            if "Graph:CONTAINS" in cypher:
                return [{"a": a, "b": b} for a, b in contains if a in ids and b in ids]
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
                skip_nested=skip_nested,
            )

    CANDIDATES = [_dir(GUI), _dir(GUI_SRC), _dir(CORE), _dir(CORE_CRUD), _dir(UTIL)]
    CONTAINS = [(GUI, GUI_SRC), (CORE, CORE_CRUD)]
    FILES = {GUI: 340, GUI_SRC: 337, CORE: 409, CORE_CRUD: 54, UTIL: 10}

    def test_a_directory_holding_nearly_all_of_its_ancestors_files_is_left_out(self):
        result = self._generate(self.CANDIDATES, self.CONTAINS, self.FILES, SOURCE)

        stages = {d.node_id: d.stage for d in result.candidate_decisions}
        assert stages[GUI_SRC] == "nested_removed"
        # A package holding a part of its module stays, and so do the modules
        assert {stages[n] for n in (GUI, CORE, CORE_CRUD, UTIL)} == {"llm_rejected"}

    def test_without_the_param_every_candidate_stays(self):
        result = self._generate(self.CANDIDATES, self.CONTAINS, self.FILES, None)

        assert "nested_removed" not in {d.stage for d in result.candidate_decisions}

    def test_the_nearest_kept_ancestor_decides(self):
        # core holds 100 files, crud half of them, and crud's own package nearly all of crud's
        assoc = "dir::r::core_crud_assoc"
        files = {CORE: 100, CORE_CRUD: 50, assoc: 48}
        contains = [(CORE, CORE_CRUD), (CORE, assoc), (CORE_CRUD, assoc)]

        result = self._generate([_dir(CORE), _dir(CORE_CRUD), _dir(assoc)], contains, files, SOURCE)

        stages = {d.node_id: d.stage for d in result.candidate_decisions}
        assert stages[CORE_CRUD] == "llm_rejected"
        assert stages[assoc] == "nested_removed"

    def test_a_left_out_directory_frees_no_place(self):
        # The cut already chose the candidates: the next one in rank does not move up
        result = self._generate([_dir(GUI), _dir(GUI_SRC), _dir(UTIL)], self.CONTAINS, self.FILES, SOURCE, max_candidates=2)

        stages = {d.node_id: d.stage for d in result.candidate_decisions}
        assert stages[GUI_SRC] == "nested_removed"
        assert stages[UTIL] == "over_cap"

    def test_an_ancestor_without_files_of_the_type_represents_nothing(self):
        result = self._generate([_dir(GUI), _dir(GUI_SRC)], self.CONTAINS, {}, SOURCE)

        assert "nested_removed" not in {d.stage for d in result.candidate_decisions}


class TestNestedQueries:
    """Files of the type are counted through containment, over any depth, on a real graph."""

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def test_nested_directories_on_a_real_graph(self, graph):
        from deriva.adapters.graph.models import DirectoryNode, FileNode

        dirs = {GUI: "r/gui", GUI_SRC: "r/gui/src", "dir::r::gui_src_app": "r/gui/src/app", UTIL: "r/util"}
        for node_id, path in dirs.items():
            graph.add_node(DirectoryNode(name=path.rsplit("/", 1)[-1], path=path, repository_name="r"), node_id=node_id)
        graph.add_edge(src_id=GUI, dst_id=GUI_SRC, relationship="CONTAINS")
        graph.add_edge(src_id=GUI_SRC, dst_id="dir::r::gui_src_app", relationship="CONTAINS")
        files = [
            (GUI, "r/gui/main.ts", "source"),
            (GUI, "r/gui/build.json", "config"),
            (GUI_SRC, "r/gui/src/a.ts", "source"),
            ("dir::r::gui_src_app", "r/gui/src/app/b.ts", "source"),
            ("dir::r::gui_src_app", "r/gui/src/app/c.ts", "source"),
            (UTIL, "r/util/d.ts", "source"),
        ]
        for parent, path, file_type in files:
            file_id = f"file::r::{path}"
            graph.add_node(FileNode(name=path.rsplit("/", 1)[-1], path=path, repository_name="r", file_type=file_type), node_id=file_id)
            graph.add_edge(src_id=parent, dst_id=file_id, relationship="CONTAINS")

        candidates = [_dir(GUI), _dir(GUI_SRC), _dir(UTIL)]
        # src holds 3 of gui's 4 source files (the config file does not count)
        assert Derivation()._nested_in_ancestors(candidates, NestedFilter(file_type="source", min_share=0.75), graph) == {GUI_SRC}
        assert Derivation()._nested_in_ancestors(candidates, NestedFilter(file_type="source", min_share=0.8), graph) == set()
