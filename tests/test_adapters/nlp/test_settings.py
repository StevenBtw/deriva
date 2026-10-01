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
