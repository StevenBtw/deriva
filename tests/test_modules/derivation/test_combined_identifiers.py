"""Element identifiers in combined runs: several repositories in one graph keep the repository in the identifier, so two
repositories' frontend, docs or customer stay two elements; a run over one repository keeps today's identifiers."""

from __future__ import annotations

import pytest

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Element
from deriva.modules.derivation.base import element_identifier, repository_in_identifiers


class TestIdentifier:
    def test_one_repository_keeps_todays_identifier(self):
        assert element_identifier("ApplicationComponent", "unit::shop::frontend") == "ac_frontend"

    def test_a_combined_run_keeps_the_repository(self):
        with repository_in_identifiers(True):
            shop = element_identifier("ApplicationComponent", "unit::shop::frontend")
            clinic = element_identifier("ApplicationComponent", "unit::clinic::frontend")
        assert (shop, clinic) == ("ac_shop__frontend", "ac_clinic__frontend")
        # Outside the run the default applies again
        assert element_identifier("ApplicationComponent", "unit::shop::frontend") == "ac_frontend"

    def test_a_source_without_a_repository_part_is_unchanged(self):
        with repository_in_identifiers(True):
            assert element_identifier("BusinessFunction", "function::Billing") == element_identifier("BusinessFunction", "function::Billing")
        assert element_identifier("BusinessFunction", "function::Billing") == "bf_function__billing"


class _Graph:
    def __init__(self, repositories: int) -> None:
        self.repositories = repositories

    def query(self, cypher, params=None):
        return [{"n": self.repositories}]


@pytest.mark.parametrize(("repositories", "combined"), [(1, False), (2, True), (0, False)])
def test_the_service_switches_by_the_repositories_in_the_graph(repositories, combined):
    from deriva.services.derivation import combined_run

    assert combined_run(_Graph(repositories)) is combined


@pytest.fixture
def am():
    from deriva.adapters.grafeo.manager import close_database

    close_database()
    manager = ArchimateManager()
    manager.connect()
    yield manager
    manager.disconnect()
    close_database()


def test_an_element_from_another_source_on_the_same_identifier_is_reported(am, caplog):
    am.add_element(Element(name="Frontend", element_type="ApplicationComponent", identifier="ac_frontend", properties={"source": "unit::shop::frontend"}))
    with caplog.at_level("WARNING"):
        am.add_element(Element(name="Frontend", element_type="ApplicationComponent", identifier="ac_frontend", properties={"source": "unit::shop::frontend"}))
        assert "replaces" not in caplog.text
        am.add_element(Element(name="Frontend", element_type="ApplicationComponent", identifier="ac_frontend", properties={"source": "unit::clinic::frontend"}))
    assert "ac_frontend" in caplog.text and "unit::shop::frontend" in caplog.text and "replaces" in caplog.text


def test_a_module_beside_its_unit_keeps_its_repository_too():
    """The module variant of candidate_identifier: two repositories' modules of a same-named unit stay two."""
    from deriva.modules.derivation.base import candidate_identifier

    sources = ["unit::repoA::svc", "module::repoA::svc", "unit::repoB::svc", "module::repoB::svc"]
    with repository_in_identifiers(True):
        ids = [candidate_identifier("ApplicationComponent", s, sources) for s in sources]
    assert len(set(ids)) == 4
    assert candidate_identifier("ApplicationComponent", "module::repoA::svc", ["unit::repoA::svc", "module::repoA::svc"]) == "ac_module__svc"
