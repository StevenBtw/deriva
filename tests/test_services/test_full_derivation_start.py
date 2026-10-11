"""Full derivation runs start from an empty model (the benchmark protocol), unless the setting is switched off.

A run on top of an earlier model skips every candidate that model already has, so it derives fewer elements and
relationships than a run from an empty model.
"""

from __future__ import annotations

from typing import Any

import pytest

from deriva.services import config, derivation


class _Session:
    """The two session methods the start check uses: a setting and clearing the model."""

    def __init__(self, setting: str | None) -> None:
        self.setting = setting
        self.cleared = 0
        self.asked: list[str] = []

    def get_setting(self, key: str) -> str | None:
        self.asked.append(key)
        return self.setting

    def clear_model(self) -> dict[str, Any]:
        self.cleared += 1
        return {"success": True}


@pytest.mark.parametrize(("value", "expected"), [(None, True), ("true", True), ("on", True), ("false", False), ("False", False), ("0", False), ("no", False), (" off ", False)])
def test_the_setting_is_on_unless_switched_off(value, expected):
    assert config.clear_model_before_derivation(value) is expected


def test_a_full_run_clears_the_model_by_default():
    session = _Session(setting=None)

    assert derivation.start_full_derivation(session) is True
    assert session.cleared == 1
    assert session.asked == [config.CLEAR_MODEL_SETTING]


def test_a_full_run_keeps_the_model_when_the_setting_is_off():
    session = _Session(setting="false")

    assert derivation.start_full_derivation(session) is False
    assert session.cleared == 0
