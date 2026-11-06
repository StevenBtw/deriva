"""Verbs of status values: a state written as a past participle (APPROVED, WRITTEN_OFF) names what happened."""

from __future__ import annotations

import pytest

from deriva.adapters.nlp.verbs import state_verbs, verb_from_tokens


def test_a_participle_gives_its_verb_with_its_particle():
    assert verb_from_tokens([("approved", "approve", "VBD")]) == "Approve"
    assert verb_from_tokens([("written", "write", "VBN"), ("off", "off", "RP")]) == "Write Off"
    # "back" is an adverb, no particle: the simple rule takes the participle alone (REFERRED_BACK is Refer)
    assert verb_from_tokens([("referred", "refer", "VBD"), ("back", "back", "RB"), ("later", "late", "RBR")]) == "Refer"


def test_a_state_that_is_no_participle_gives_no_verb():
    assert verb_from_tokens([("in", "in", "IN"), ("port", "port", "NN")]) is None
    assert verb_from_tokens([("pending", "pende", "VBG"), ("assessment", "assessment", "NN")]) is None
    assert verb_from_tokens([]) is None


def test_without_the_english_model_no_state_gets_a_verb(tmp_path):
    assert state_verbs(["APPROVED"], tmp_path) == {}


@pytest.mark.integration
def test_status_values_read_with_the_english_model():
    from deriva.adapters.nlp import NlpTool

    verbs = state_verbs(["SUBMITTED", "DISBURSED", "CHARGED_OFF", "IN_PORT"], NlpTool().models_dir)
    assert verbs == {"SUBMITTED": "Submit", "DISBURSED": "Disburse", "CHARGED_OFF": "Charge Off"}


def test_an_adverb_after_the_participle_is_no_part_of_the_verb():
    """APPROVED_AUTOMATICALLY is approved; "Approve Automatically Loan" is no process name."""
    assert verb_from_tokens([("approved", "approve", "VBN"), ("automatically", "automatically", "RB")]) == "Approve"
    assert verb_from_tokens([("closed", "close", "VBD"), ("manually", "manually", "RB")]) == "Close"
    assert verb_from_tokens([("locked", "lock", "VBD"), ("out", "out", "RP"), ("permanently", "permanently", "RB")]) == "Lock Out"


def test_a_split_prefix_is_no_verb():
    """RE_OPENED: the tagger reads "re" as a past tense; "Re" is no verb."""
    assert verb_from_tokens([("re", "re", "VBD"), ("opened", "open", "VBN")]) in (None, "Reopen")


def test_no_states_give_no_verbs(tmp_path):
    assert state_verbs([], tmp_path) == {}


@pytest.mark.integration
def test_adverbs_and_prefixes_with_the_english_model():
    from deriva.adapters.nlp import NlpTool

    verbs = state_verbs(["APPROVED_AUTOMATICALLY", "SETTLED_EARLY", "HANDED_OVER", "RE_OPENED", "A", "V2", "ON_HOLD"], NlpTool().models_dir)
    assert verbs.get("APPROVED_AUTOMATICALLY") == "Approve" and verbs.get("SETTLED_EARLY") == "Settle"
    assert verbs.get("HANDED_OVER") == "Hand Over"
    assert verbs.get("RE_OPENED") in (None, "Reopen")
    assert not {"A", "V2", "ON_HOLD"} & set(verbs)


@pytest.mark.integration
def test_a_state_s_verb_does_not_depend_on_the_words_after_its_participle():
    """CLOSED_WRITTEN_OFF read alone as "closed written off" lemmatizes "closed" to itself ("Closed Loan" beside
    "Close Loan" in one lifecycle); every state that starts with CLOSED says Close."""
    from deriva.adapters.nlp import NlpTool

    verbs = state_verbs(["CLOSED", "CLOSED_WRITTEN_OFF", "CLOSED_OBLIGATIONS_MET"], NlpTool().models_dir)

    assert verbs == {"CLOSED": "Close", "CLOSED_WRITTEN_OFF": "Close", "CLOSED_OBLIGATIONS_MET": "Close"}
