import pytest

from deriva.adapters.nlp.settings import Settings


class TestSettings:
    def test_values_come_from_the_config(self):
        assert Settings.from_dict({"dedup_shingle": 4}).dedup_shingle == 4

    def test_an_unknown_name_is_an_error(self):
        with pytest.raises(ValueError, match="Unknown settings: dedup_shingles"):
            Settings.from_dict({"dedup_shingles": 4})

    @pytest.mark.parametrize("size", [0, -1])
    def test_a_shingle_below_one_word_is_an_error(self, size):
        # Every segment would share the empty shingle and count as a duplicate
        with pytest.raises(ValueError, match="dedup_shingle"):
            Settings.from_dict({"dedup_shingle": size})


def test_a_switch_takes_true_or_false_and_prepositions_a_list_of_words():
    assert Settings.from_dict({"noun_proper": True}).noun_proper is True
    for bad in ({"noun_hyphens": "false"}, {"leading_verbs": 1}, {"verb_prepositions": "for"}, {"verb_prepositions": [1]}):
        with pytest.raises(ValueError):
            Settings.from_dict(bad)


@pytest.mark.parametrize(("name", "value"), [("max_noun_tokens", True), ("max_noun_tokens", "3"), ("max_noun_tokens", 2.5), ("dedup_jaccard", "0.8"), ("dedup_jaccard", False)])
def test_a_number_of_the_wrong_type_is_refused(name, value):
    with pytest.raises(ValueError, match=name):
        Settings.from_dict({name: value})


def test_a_whole_number_is_a_valid_share():
    assert Settings.from_dict({"dedup_jaccard": 1}).dedup_jaccard == 1
