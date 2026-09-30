"""Tests for modules.extraction.business_concept: concept identity and order-independent merging."""

from __future__ import annotations

import json

from deriva.modules.extraction.business_concept import concept_node_id


class TestConceptNodeId:
    def test_one_id_for_every_spelling_of_a_name(self):
        assert concept_node_id("r", "Data Sources") == concept_node_id("r", "data_source") == "concept::r::datasource"


class TestMergeConceptProperties:
    """One concept seen in several files: the combined node must not depend on file order."""

    README = {"conceptName": "User", "conceptType": "entity", "confidence": 0.9, "description": "from readme", "originSource": "README.md"}
    RTF = {"conceptName": "User", "conceptType": "actor", "confidence": 0.9, "description": "from requirements", "originSource": "docs/requirements.rtf"}
    DOC = {"conceptName": "User", "conceptType": "actor", "confidence": 0.7, "description": "weak", "originSource": "docs/a.md"}

    @staticmethod
    def _fold(occurrences):
        from deriva.modules.extraction.business_concept import merge_concept_properties

        merged = None
        for o in occurrences:
            merged = merge_concept_properties(merged, o)
        return merged

    def test_all_types_are_kept(self):
        merged = self._fold([self.README, self.RTF])

        assert merged["conceptTypes"] == ["actor", "entity"]
        assert merged["confidence"] == 0.9

    def test_result_is_independent_of_order(self):
        import itertools

        results = {json.dumps(self._fold(p), sort_keys=True) for p in itertools.permutations([self.README, self.RTF, self.DOC])}

        assert len(results) == 1

    def test_primary_fields_come_from_the_strongest_occurrence(self):
        merged = self._fold([self.DOC, self.README])

        assert (merged["conceptType"], merged["description"], merged["originSource"]) == ("entity", "from readme", "README.md")

    def test_single_occurrence_gets_its_type_as_the_set(self):
        assert self._fold([self.DOC])["conceptTypes"] == ["actor"]

    def test_source_terms_of_every_occurrence_are_kept(self):
        merged = self._fold([{**self.README, "sourceTerms": ["User (en)"]}, {**self.RTF, "sourceTerms": ["Benutzer (de)"]}])

        assert merged["sourceTerms"] == ["Benutzer (de)", "User (en)"]
