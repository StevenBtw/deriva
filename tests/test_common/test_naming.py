"""Tests for the canonical name key (one identity for every spelling of a name)."""

from __future__ import annotations

import pytest

from deriva.common.naming import name_key, singularize

# Generic English singular:plural pairs per rule family; each plural must come back as its singular
PAIRS = {
    "-se words add s": "database:databases case:cases phase:phases release:releases response:responses license:licenses purpose:purposes "
    "expense:expenses purchase:purchases use:uses cause:causes warehouse:warehouses enterprise:enterprises premise:premises "
    "exercise:exercises promise:promises lease:leases sense:senses pulse:pulses reuse:reuses excuse:excuses course:courses base:bases",
    "-ss words add es": "class:classes process:processes address:addresses access:accesses business:businesses success:successes loss:losses",
    "singulars ending in s add es": "alias:aliases atlas:atlases bias:biases canvas:canvases gas:gases lens:lenses bus:buses virus:viruses "
    "bonus:bonuses campus:campuses focus:focuses census:censuses consensus:consensuses surplus:surpluses corpus:corpuses status:statuses",
    "greek -sis": "analysis:analyses crisis:crises thesis:theses hypothesis:hypotheses diagnosis:diagnoses synthesis:syntheses "
    "parenthesis:parentheses emphasis:emphases synopsis:synopses",
    "-x -sh -ch -zz -tz add es": "box:boxes prefix:prefixes tax:taxes match:matches batch:batches branch:branches search:searches "
    "approach:approaches switch:switches hash:hashes crash:crashes wish:wishes buzz:buzzes waltz:waltzes",
    "-che -ze add s": "cache:caches niche:niches headache:headaches size:sizes prize:prizes maze:mazes",
    "-y after a consonant": "city:cities category:categories entity:entities policy:policies query:queries library:libraries "
    "dependency:dependencies repository:repositories property:properties strategy:strategies key:keys day:days journey:journeys",
    "-ie add s": "cookie:cookies zombie:zombies calorie:calories pie:pies tie:ties rookie:rookies selfie:selfies hoodie:hoodies",
    "-f -fe -ve": "life:lives knife:knives half:halves shelf:shelves self:selves wife:wives wolf:wolves thief:thieves archive:archives "
    "drive:drives objective:objectives initiative:initiatives executive:executives incentive:incentives curve:curves valve:valves",
    "-o": "hero:heroes echo:echoes veto:vetoes potato:potatoes embargo:embargoes cargo:cargoes photo:photos video:videos memo:memos "
    "scenario:scenarios portfolio:portfolios shoe:shoes toe:toes canoe:canoes",
    "irregular": "person:people child:children man:men woman:women foot:feet tooth:teeth mouse:mice criterion:criteria "
    "phenomenon:phenomena index:indices matrix:matrices vertex:vertices appendix:appendices curriculum:curricula stimulus:stimuli "
    "radius:radii nucleus:nuclei quiz:quizzes",
}
# Words whose singular is their only form here (mass nouns, singulars ending in s)
SINGULAR_ONLY = "data information software hardware metadata news series species analytics logistics chaos basis asynchronous continuous"


class TestSingularize:
    @pytest.mark.parametrize("singular, plural", [tuple(pair.split(":")) for pairs in PAIRS.values() for pair in pairs.split()], ids=lambda value: value)
    def test_a_plural_and_its_singular_share_one_form(self, singular, plural):
        assert (singularize(plural), singularize(singular)) == (singular, singular)

    @pytest.mark.parametrize("word", SINGULAR_ONLY.split())
    def test_singular_only_words_stay(self, word):
        assert singularize(word) == word

    @pytest.mark.parametrize("plural, singular", [("Databases", "Database"), ("Aliases", "Alias"), ("CACHES", "CACHE"), ("Cities", "City"), ("Men", "Man")])
    def test_the_case_is_kept(self, plural, singular):
        assert singularize(plural) == singular


class TestNameKey:
    @pytest.mark.parametrize(
        "spellings",
        [
            ["Claims Handling", "ClaimsHandling", "claims_handling", "claims-handling", "CLAIMS HANDLING"],
            ["HTTPServer", "HTTP Server", "http_server"],
            ["Realtime Streaming", "RealTimeStreaming", "Real Time Streaming"],
            ["Data Sources", "DataSource", "data source"],
        ],
    )
    def test_spellings_of_one_name_share_a_key(self, spellings):
        assert len({name_key(s) for s in spellings}) == 1

    def test_every_word_is_singular(self):
        """Plural words inside a compound drift too ("LikesAggregation" / "Like Aggregation")."""
        assert name_key("LikesAggregation") == name_key("Like Aggregation") == "likeaggregation"

    def test_the_last_word_is_singular(self):
        assert name_key("Orders") == name_key("Order") == "order"

    def test_singular_and_plural_forms_of_a_compound_share_a_key(self):
        assert name_key("Database Backups") == name_key("DatabaseBackup") == "databasebackup"
        assert name_key("Cache Entries") == name_key("cache_entry") == "cacheentry"

    def test_parenthetical_asides_are_dropped(self):
        assert name_key("Service Discovery (registry)") == name_key("Service Discovery")

    def test_letters_of_every_script_are_kept(self):
        assert name_key("Café") == "café"

    def test_uncountable_words_stay(self):
        assert name_key("Series") == "series"
        assert name_key("Analysis") == "analysis"

    def test_different_names_keep_different_keys(self):
        assert name_key("Order Line") != name_key("Order")

    def test_empty(self):
        assert name_key("") == ""
        assert name_key("  (aside) ") == ""
