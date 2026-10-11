"""Files with one name in several directories are different candidates (a routes file per service), not duplicates."""

from __future__ import annotations

from deriva.modules.derivation.base import Candidate
from deriva.modules.derivation.element_base import ElementDerivationBase, distinct_candidate_names


def _file(path: str, pagerank: float = 0.0) -> Candidate:
    name = path.rsplit("/", 1)[-1]
    return Candidate(node_id="file::r::" + path.replace("/", "_"), name=name, labels=["Graph", "File"], properties={"filePath": path}, pagerank=pagerank)


ALPHA = _file("services/alpha-service/app/routes.py", 0.3)
BETA = _file("services/beta-service/app/routes.py", 0.2)
GAMMA = _file("services/gamma-service/app/routes.py", 0.1)
MAIN = _file("gateway/main.py")
TYPE_A = Candidate(node_id="typedef::r::a/Entry.java::Entry", name="Entry", labels=["Graph", "TypeDefinition"], properties={"filePath": "a/Entry.java"})
TYPE_B = Candidate(node_id="typedef::r::b/Entry.java::Entry", name="Entry", labels=["Graph", "TypeDefinition"], properties={"filePath": "b/Entry.java"})


class Derivation(ElementDerivationBase):
    ELEMENT_TYPE = "ApplicationInterface"

    def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
        return candidates[:max_candidates]


class TestDistinctNames:
    def test_same_named_files_are_told_apart_by_the_directory_that_differs(self):
        names = distinct_candidate_names([ALPHA, BETA, GAMMA, MAIN])

        assert names[ALPHA.node_id] == "alpha-service routes.py"
        assert names[BETA.node_id] == "beta-service routes.py"
        assert names[MAIN.node_id] == "main.py"

    def test_types_keep_their_name(self):
        """The same type name in two places may be one concept: only files are qualified."""
        names = distinct_candidate_names([TYPE_A, TYPE_B])

        assert names == {TYPE_A.node_id: "Entry", TYPE_B.node_id: "Entry"}

    def test_files_without_a_path_keep_their_name(self):
        bare = Candidate(node_id="file::r::x_routes.py", name="routes.py", labels=["Graph", "File"])

        assert distinct_candidate_names([bare, ALPHA])[bare.node_id] == "routes.py"


class TestConsolidation:
    def test_a_routes_file_per_service_stays_a_candidate_per_service(self):
        kept = Derivation()._consolidate_near_duplicates([ALPHA, BETA, GAMMA])

        assert {c.node_id for c in kept} == {ALPHA.node_id, BETA.node_id, GAMMA.node_id}

    def test_same_named_types_are_still_merged(self):
        kept = Derivation()._consolidate_near_duplicates([TYPE_A, TYPE_B])

        assert len(kept) == 1


class TestCodes:
    """Names that differ in a code (a word with a digit, or in capitals) name different things, however alike they look."""

    def test_names_that_differ_in_a_code_are_told_apart(self):
        from deriva.modules.derivation.refine.base import differ_in_a_code

        assert differ_in_a_code("Maps SCRN0A Web UI", "Maps SCRN1A Web UI")
        assert differ_in_a_code("Maps LSTA Web UI", "Maps LSTB Web UI")
        assert differ_in_a_code("Ledger HTTP API", "Ledger CLI")
        assert not differ_in_a_code("Ledger Entry Storage", "Ledger Entries Storage")
        assert not differ_in_a_code("Maps SCRN0A Web UI", "Maps SCRN0A Web UI Page")

    def test_candidates_with_different_codes_are_not_merged(self):
        one = Candidate(node_id="typedef::r::maps/A.bms::SCRN0A", name="SCRN0A", labels=["Graph", "TypeDefinition"])
        two = Candidate(node_id="typedef::r::maps/B.bms::SCRN1A", name="SCRN1A", labels=["Graph", "TypeDefinition"])

        assert len(Derivation()._consolidate_near_duplicates([one, two])) == 2


def test_a_word_that_differs_in_case_only_is_no_other_code():
    from deriva.modules.derivation.refine.base import differ_in_a_code

    assert not differ_in_a_code("User HTTP request", "Users http requests")
    assert differ_in_a_code("User HTTP request", "User CLI request")


def test_same_named_files_in_one_container_are_told_apart_by_their_directory():
    """Two routes files of one component used to plan the same name, and the second was left out."""
    from tests.test_modules.derivation.test_roles import TestRoleNameTemplate

    a = TestRoleNameTemplate._file("routes.py", "shop/ledgers/routes.py")
    b = TestRoleNameTemplate._file("routes.py", "shop/parcels/routes.py")
    other = TestRoleNameTemplate._file("commands.py", "shop/commands.py")

    elements, _ = TestRoleNameTemplate._generate([a, b, other], {a.node_id: "http", b.node_id: "http", other.node_id: "cli"}, [("dir::r::shop", "shop", "Shop")])

    assert sorted(e["name"] for e in elements.values()) == ["Shop Commands CLI", "Shop Ledgers Routes HTTP API", "Shop Parcels Routes HTTP API"]
