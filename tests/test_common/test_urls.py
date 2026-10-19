"""Credentials in URLs: the user and token part goes, the rest stays readable."""

from __future__ import annotations

import pytest

from deriva.common.urls import redact_credentials


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://user:s3cret@github.com/org/x.git", "https://github.com/org/x.git"),
        ("https://ghp_token123@github.com/org/x.git", "https://github.com/org/x.git"),
        ("fatal: repository 'https://u:p@host.example/a/b.git/' not found", "fatal: repository 'https://host.example/a/b.git/' not found"),
        ("two: http://a:b@one.example/x and https://c@two.example/y", "two: http://one.example/x and https://two.example/y"),
    ],
)
def test_the_user_and_token_part_of_a_url_goes(text, expected):
    assert redact_credentials(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "https://github.com/org/x.git",
        "git@github.com:org/x.git",
        "ssh://git@github.com/org/x.git",
        "file:///C:/repos/x.git",
        "mail me at someone@example.com",
        "",
    ],
)
def test_text_without_credentials_stays_as_it_is(text):
    """An SSH user is no secret (the key is), and an address outside a URL is no URL."""
    assert redact_credentials(text) == text
