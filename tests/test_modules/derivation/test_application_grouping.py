"""Application grouping: the documentation's headings as closed candidates, one LLM choice per component, verified by
structure with a fallback to the component's own name."""

from __future__ import annotations

import json

from deriva.modules.derivation.application_grouping import (
    applications,
    build_grouping_prompt,
    doc_headings,
    grouping_candidates,
    grouping_schema,
    parse_grouping,
    title_parts,
)

README = """# ![logo](x.png) Shop System - Online Store Application

Intro text.

## Architecture

The `front` and the `back` units, and the orders domain.

```text
# not a heading
```

## Running

Start the back unit.
"""


def test_headings_list_their_level_clean_text_and_the_units_or_domains_their_section_mentions():
    headings = doc_headings({"r/README.md": README}, {"u_front": {"front"}, "u_back": {"back"}, "d_orders": {"orders"}})

    assert [(h.level, h.text, sorted(h.mentions)) for h in headings] == [
        (1, "Shop System - Online Store Application", []),
        (2, "Architecture", ["d_orders", "u_back", "u_front"]),
        (2, "Running", ["u_back"]),
    ]


def test_the_root_readme_title_splits_at_its_dash_and_the_candidates_follow_title_then_component_names():
    titles = title_parts({"r/README.md": README, "r/back/README.md": "# Back"}, "r")

    assert titles == ["Shop System", "Online Store Application"]
    assert grouping_candidates(titles, ["Front", "Back", "shop system"]) == ["Shop System", "Online Store Application", "Front", "Back"]


def test_the_choice_is_verified_and_a_missing_or_foreign_answer_falls_back_to_the_components_own_name():
    candidates = ["Shop System", "Front", "Back", "Other"]
    fallback = {"c_front": "Front", "c_back": "Back", "c_other": "Other"}
    answer = json.dumps({"assignments": {"c_front": "Shop System", "c_back": "Shop System", "c_other": "Invented Name"}})

    assignment = parse_grouping(answer, fallback, candidates)

    assert assignment == {"c_front": "Shop System", "c_back": "Shop System", "c_other": "Other"}
    assert parse_grouping("not json", fallback, candidates) == fallback
    # Only a candidate two or more components choose becomes an application
    assert applications(assignment) == [("Shop System", ["c_back", "c_front"])]


def test_the_prompt_and_schema_depend_only_on_structure_and_close_the_set_per_component():
    components = [{"key": "c_back", "name": "Back", "folder": "r/back", "title": "Back"}, {"key": "c_front", "name": "Front", "folder": "r/front", "title": ""}]

    prompt = build_grouping_prompt("Group the components.", components, ["Shop System", "Front", "Back"])
    schema = grouping_schema(["c_back", "c_front"], ["Shop System", "Front", "Back"])

    assert prompt.startswith("Group the components.") and '"c_back"' in prompt and '- "Shop System"' in prompt
    assignments = schema["schema"]["properties"]["assignments"]
    assert assignments["required"] == ["c_back", "c_front"] and assignments["properties"]["c_front"]["enum"] == ["Shop System", "Front", "Back"]


def test_the_root_readmes_introduction_is_the_text_under_its_title_without_markup_and_capped():
    from deriva.modules.derivation.application_grouping import introduction

    text = "# Shop\n\n![badge](b.svg)\nA [shop](http://x) made of **two** parts.\n\nMore text here.\n\n## Next\nignored\n"

    assert introduction({"r/README.md": text}, "r", 200) == "A shop made of two parts. More text here."
    assert introduction({"r/README.md": text}, "r", 10) == "A shop mad"
    assert "## Repository documentation" in build_grouping_prompt("Group.", [], ["A"], documentation="A shop.")
    prompt = build_grouping_prompt("Group.", [], ["Shop System", "Front"], whole=1)
    assert prompt.index('- "Shop System"') < prompt.index("naming one component") < prompt.index('- "Front"')


def test_a_components_own_name_drops_its_kind_words_and_keeps_its_punctuation():
    from deriva.modules.derivation.application_grouping import own_name

    kinds = ("Backend", "Frontend", "Server")

    assert own_name("Customer Self-Service Backend", kinds) == "Customer Self-Service"
    assert own_name("Risk Management Server", kinds) == "Risk Management"
    assert own_name("Backend", kinds) == "Backend"  # nothing left: the name stays


def test_the_title_name_is_marked_when_the_title_has_more_parts():
    prompt = build_grouping_prompt("Group.", [], ["Shop System", "Online Store", "Front"], whole=2, mark_name=True)

    assert '- "Shop System" (the name in the title)' in prompt and '- "Online Store"\n' in prompt
