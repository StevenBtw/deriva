"""Business actors from documentation: the extraction's actor concepts as closed candidates per application, verified
by a documentation section that mentions both, one closed multi-choice per repository with "none" allowed."""

from __future__ import annotations

import json

from deriva.modules.derivation.documentation_actors import actor_evidence, actor_schema, build_actor_prompt, parse_actors, verified_candidates

DOCS = {
    "r/README.md": "# Shop\n\n## Ordering\n\nA shopper orders tea in the `front` unit.\n\n## Operations\n\nA user restarts the jobs.\n",
    "r/jobs/README.md": "# Jobs\n\nNightly batch.\n",
}


def test_a_candidate_counts_for_an_application_only_where_one_section_mentions_both():
    applications = {"app_shop": {"front", "shop"}, "app_jobs": {"jobs"}}
    concepts = {"concept::shopper": "Shopper", "concept::user": "User", "concept::auditor": "Auditor"}

    assert verified_candidates(DOCS, applications, concepts) == {"app_shop": ["concept::shopper"], "app_jobs": ["concept::user"]}


def test_the_choice_keeps_only_listed_candidates_and_none_is_an_empty_list():
    candidates = {"app_shop": ["Shopper", "User"], "app_jobs": ["User"]}
    answer = json.dumps({"actors": {"app_shop": ["Shopper", "Invented"], "app_jobs": []}})

    assert parse_actors(answer, candidates) == {"app_shop": ["Shopper"], "app_jobs": []}
    assert parse_actors("not json", candidates) == {"app_shop": [], "app_jobs": []}


def test_the_prompt_and_schema_close_the_set_per_application():
    candidates = {"app_shop": ["Shopper", "User"]}

    prompt = build_actor_prompt("Choose.", [{"key": "app_shop", "name": "Shop", "units": ["r/front"]}], candidates, documentation="A shop.")
    schema = actor_schema(candidates)

    assert prompt.startswith("Choose.") and "## Repository documentation" in prompt and '"Shopper"' in prompt
    items = schema["schema"]["properties"]["actors"]["properties"]["app_shop"]
    assert items["type"] == "array" and items["items"]["enum"] == ["Shopper", "User"]


def test_the_evidence_is_the_first_sentence_that_names_the_candidate_with_the_application():
    """Per application and candidate, one sentence of a section that mentions both: one that also names the application
    first, else one that names the candidate; markup and fenced code left out, with its file and heading."""
    docs = {
        "r/README.md": "# Shop\n\n## Ordering\n\nA user browses. In the `front` unit a **shopper** orders tea. Done.\n\n```\nshopper front\n```\n",
        "r/docs/b.md": "# Later\n\nThe front shows a shopper the bill.\n",
    }
    verified = {"app_shop": ["concept::shopper", "concept::user"]}
    concepts = {"concept::shopper": "Shopper", "concept::user": "User"}

    evidence = actor_evidence(docs, {"app_shop": {"front", "shop"}}, concepts, verified, max_chars=200)

    assert evidence == {
        "app_shop": {
            "Shopper": 'In the front unit a shopper orders tea. (r/README.md, "Ordering")',
            "User": 'A user browses. (r/README.md, "Ordering")',
        }
    }


def test_a_sentence_that_names_both_wins_over_an_earlier_section_and_table_rows_are_no_evidence():
    docs = {
        "r/README.md": "# Shop\n\n## Shop files\n\n| shopper.dat | shopper file |\n\nThe shopper data is kept.\n\n## Use\n\nA shopper buys tea in the shop.\n",
    }

    found = actor_evidence(docs, {"app_shop": {"shop"}}, {"concept::shopper": "Shopper"}, {"app_shop": ["concept::shopper"]}, max_chars=200)

    assert found == {"app_shop": {"Shopper": 'A shopper buys tea in the shop. (r/README.md, "Use")'}}
    only_table = {"r/README.md": "# Shop\n\n| shopper | shop |\n"}
    assert actor_evidence(only_table, {"app_shop": {"shop"}}, {"concept::shopper": "Shopper"}, {"app_shop": ["concept::shopper"]}, max_chars=200) == {}


def test_a_glossary_term_stays_with_its_definition():
    docs = {"r/README.md": "# Shop\n\n* **Shopper.** A Shopper buys tea in the shop.\n"}

    found = actor_evidence(docs, {"app_shop": {"shop"}}, {"concept::shopper": "Shopper"}, {"app_shop": ["concept::shopper"]}, max_chars=200)

    assert found == {"app_shop": {"Shopper": 'Shopper: A Shopper buys tea in the shop. (r/README.md, "Shop")'}}


def test_a_long_evidence_sentence_is_cut_around_the_candidate():
    docs = {"r/README.md": "# Shop\n\n" + "word " * 60 + "and the front serves a shopper well " + "word " * 60 + ".\n"}
    found = actor_evidence(docs, {"app_shop": {"front"}}, {"concept::shopper": "Shopper"}, {"app_shop": ["concept::shopper"]}, max_chars=60)

    sentence = found["app_shop"]["Shopper"].split(" (r/README.md")[0]

    assert "shopper" in sentence and sentence.startswith("...") and sentence.endswith("...") and len(sentence) <= 66


def test_the_prompt_shows_the_evidence_per_candidate_and_without_it_stays_as_before():
    candidates = {"app_shop": ["Shopper", "User"]}
    apps = [{"key": "app_shop", "name": "Shop", "units": ["r/front"]}]
    evidence = {"app_shop": {"Shopper": 'A shopper orders. (r/README.md, "Ordering")'}}

    shown = build_actor_prompt("Choose.", apps, candidates, evidence=evidence)

    assert '## Evidence per candidate\n- app_shop:\n  - Shopper: A shopper orders. (r/README.md, "Ordering")\n' in shown
    assert build_actor_prompt("Choose.", apps, candidates) == build_actor_prompt("Choose.", apps, candidates, evidence={})
    assert "## Evidence" not in build_actor_prompt("Choose.", apps, candidates)


def test_evidence_names_an_application_written_with_an_underscore():
    """A unit word with an underscore (order_service) is still found in the sentence once its code marks are gone, so
    the sentence that names both the candidate and the application is the evidence."""
    docs = {"r/README.md": "# Shop\n\n## Use\n\nA Shopper browses the catalog. A Shopper places orders through `order_service`.\n"}

    found = actor_evidence(docs, {"app_shop": {"order_service"}}, {"concept::shopper": "Shopper"}, {"app_shop": ["concept::shopper"]}, max_chars=200)

    assert found["app_shop"]["Shopper"].startswith("A Shopper places orders through order_service.")


def test_a_word_only_in_fenced_code_is_no_mention():
    """A section that names the application or the candidate only inside fenced code mentions neither: no candidate
    for verification, no section for evidence."""
    fence = "`" * 3
    docs = {"r/README.md": f"# Shop\n\n## Setup\n\nRun the service.\n\n{fence}\nshopper front\n{fence}\n\n## Use\n\nA shopper buys tea.\n"}

    assert verified_candidates(docs, {"app_shop": {"front"}}, {"concept::shopper": "Shopper"}) == {}
    assert actor_evidence(docs, {"app_shop": {"front"}}, {"concept::shopper": "Shopper"}, {"app_shop": ["concept::shopper"]}, max_chars=200) == {}
