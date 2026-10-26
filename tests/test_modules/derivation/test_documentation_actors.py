"""Business actors from documentation: the extraction's actor concepts as closed candidates per application, verified
by a documentation section that mentions both, one closed multi-choice per repository with "none" allowed."""

from __future__ import annotations

import json

from deriva.modules.derivation.documentation_actors import actor_schema, build_actor_prompt, parse_actors, verified_candidates

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
