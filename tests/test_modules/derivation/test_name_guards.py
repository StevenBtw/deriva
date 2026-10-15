"""Guards on a naming call's answer: structure decides when the answer collides or says nothing (rule 6c)."""

from __future__ import annotations

from deriva.modules.derivation.base import NameGuards, guard_name

GUARDS = NameGuards(
    generic_words=frozenset({"application", "app", "cli", "server", "backend", "frontend", "service", "web", "ui"}),
    kind_nouns={"container": "Server", "*": "Application"},
)


def test_an_answer_that_names_a_technology_gets_the_structure_name():
    name = guard_name("Spring Boot Admin", structure_name="Admin Console", kind="container", product="Shop", reserved={"spring boot admin"}, guards=GUARDS)

    assert name == "Admin Console"


def test_a_structure_name_that_collides_too_gets_the_noun_of_its_unit_kind():
    assert (
        guard_name("Spring Boot Admin", structure_name="Spring Boot Admin", kind="container", product="Shop", reserved={"spring boot admin"}, guards=GUARDS)
        == "Spring Boot Admin Server"
    )
    assert (
        guard_name("Spring Boot Admin", structure_name="Spring Boot Admin", kind="script", product="Shop", reserved={"spring boot admin"}, guards=GUARDS)
        == "Spring Boot Admin Application"
    )


def test_a_generic_answer_gets_the_product_name_in_front():
    assert guard_name("CLI", structure_name="Shop Cli", kind="script", product="Shop", reserved=set(), guards=GUARDS) == "Shop CLI"
    assert guard_name("Web Application", structure_name="Shop App", kind="script", product="Shop", reserved=set(), guards=GUARDS) == "Shop Web Application"


def test_a_specific_answer_is_kept_as_written():
    assert guard_name("Order Fulfilment", structure_name="Fulfilment", kind="container", product="Shop", reserved={"spring boot admin"}, guards=GUARDS) == "Order Fulfilment"


def test_without_guards_the_answer_is_kept():
    assert guard_name("CLI", structure_name="Shop Cli", kind="script", product="Shop", reserved={"cli"}, guards=NameGuards()) == "CLI"


def test_a_generic_answer_that_holds_a_multiword_product_gets_no_second_product():
    assert guard_name("Web App", structure_name="Web App", kind="script", product="Web App", reserved=set(), guards=GUARDS) == "Web App"
    assert guard_name("Web App Server", structure_name="Server", kind="container", product="Web App", reserved=set(), guards=GUARDS) == "Web App Server"
