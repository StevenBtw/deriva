"""URLs in text that leaves the process (errors, logs, stored records): no credentials."""

from __future__ import annotations

import re

__all__ = ["redact_credentials"]

# The user and token part of an http(s) or ftp URL ("https://user:token@host/..."); an SSH user is no secret
_CREDENTIALS = re.compile(r"\b((?:https?|ftp)://)[^/\s@'\"]+@", re.IGNORECASE)


def redact_credentials(text: str) -> str:
    """The text with the user and token part of every http(s) URL in it removed; host and path stay readable."""
    return _CREDENTIALS.sub(r"\1", text or "")
