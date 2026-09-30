"""Text preparation: generic cleanup, segments, binary and prose filters, near-duplicate removal."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from .settings import Settings

# A word with optional surrounding punctuation ("(users)", "Process,")
ALPHA_WORD = re.compile(r"[(\"'«„“‚]?[^\W\d_]+(?:[-'’][^\W\d_]+)*[)\"'»“”‘’.,;:!?]*")
LIST_ITEM = re.compile(r"^\s*(?:[-*+•>]|\d+[.)])\s+")
WORDS = re.compile(r"[^\W_]+")


def is_binary(text: str, settings: Settings) -> bool:
    """True for content that is not text (images, fonts, archives read as characters)."""
    bad = sum(1 for ch in text if (unicodedata.category(ch) in ("Cc", "Co", "Cs") and ch not in "\n\r\t") or ch == "\ufffd")
    return bad > settings.binary_share * max(1, len(text))


def _rtf_hex(match: re.Match[str]) -> str:
    return bytes([int(match.group(1), 16)]).decode("cp1252", errors="replace")


# A tag, comment, declaration or template directive: a name or one of ! ? # @ right after "<"
# (so "a < b > c" stays text); quoted attribute values may hold "<" or ">"
TAG = re.compile(r"""</?[A-Za-z!?#@][^<>"'\n]*(?:(?:"[^"\n]*"|'[^'\n]*')[^<>"'\n]*)*>""")


def _rtf_unicode(match: re.Match[str]) -> str:
    code = int(match.group(1))
    return chr(code + 65536 if code < 0 else code)


def clean(text: str) -> str:
    """Generic markup cleanup: Unicode normalization, RTF, Markdown code and links, URLs, tags, hyphenation."""
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    if text.lstrip().startswith("{\\rtf"):
        text = text.replace("\\\n", "\n")
        text = re.sub(r"\\par\b ?", "\n\n", text)  # a paragraph ends a segment
        text = re.sub(r"\\line\b ?", "\n", text)  # a line break is a soft wrap
        # \uN is the character N (negative above 32767), followed by one fallback character for readers without Unicode
        text = re.sub(r"\\u(-?\d+) ?(?:\\'[0-9a-fA-F]{2}|[^\\{}])?", _rtf_unicode, text)
        text = re.sub(r"\\'([0-9a-fA-F]{2})", _rtf_hex, text)
        text = re.sub(r"\\[a-zA-Z]+-?\d* ?|\\[^a-zA-Z\n]|[{}]", " ", text)
    text = re.sub(r"(?s)```.*?```|~~~.*?~~~", " ", text)  # fenced code
    text = re.sub(r"`[^`\n]*`", " ", text)  # inline code
    text = re.sub(r"!?\[([^\]\n]*)\]\([^)\n]*\)", r"\1", text)  # links and images keep their text
    text = TAG.sub(" ", text)  # before URLs, which would take a quote of an attribute along
    text = re.sub(r"\b(?:https?|ftp|file)://\S+|\bwww\.\S+|\S+@\S+\.\w+", " ", text)
    text = re.sub(r"(\w)-\n\s*([a-zäöüßàâçéèêëîïôûùÿœ])", r"\1\2", text)  # line-end hyphenation
    return text.replace("**", "").replace("__", "")


def _tidy(segment: str) -> str:
    segment = re.sub(r"(?<!\w)[*_#]+|[*_#]+(?!\w)", " ", segment)
    return re.sub(r"\s+", " ", segment).strip()


def segments(text: str) -> list[str]:
    """Blocks of text: blank lines, headings, list items and table cells start a new segment;
    other line breaks are soft wraps and are joined with a space."""
    out: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            out.append(" ".join(current))
            current.clear()

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            flush()
        elif stripped.startswith("#"):
            flush()
            out.append(_tidy(stripped.lstrip("#")))
        elif stripped.startswith("|"):
            flush()
            out.extend(_tidy(cell) for cell in stripped.split("|"))
        elif LIST_ITEM.match(line):
            flush()
            current.append(_tidy(LIST_ITEM.sub("", line, count=1)))
        else:
            current.append(_tidy(stripped))
    flush()
    return [s for s in out if s]


def is_prose(segment: str, settings: Settings) -> bool:
    """True when the segment is running text, not code, data or a list of symbols."""
    tokens = segment.split()
    alpha = sum(1 for t in tokens if ALPHA_WORD.fullmatch(t))
    return alpha >= settings.segment_min_words and alpha >= settings.segment_min_alpha * len(tokens)


def duplicate_segments(documents: dict[str, list[str]], settings: Settings) -> set[tuple[str, int]]:
    """(path, segment index) of segments repeated from an earlier document, in path order.

    Segments with at least one word shingle are compared by shingle Jaccard; shorter segments
    (headings, list items) by their exact word sequence. A document's own segments are only
    compared with earlier documents, so repeats within one document stay.
    """
    size = settings.dedup_shingle
    index: dict[tuple[str, ...], list[int]] = defaultdict(list)
    kept: list[frozenset[tuple[str, ...]]] = []
    short_seen: set[tuple[str, ...]] = set()
    dropped: set[tuple[str, int]] = set()
    for path in sorted(documents):
        pending: list[frozenset[tuple[str, ...]]] = []
        pending_short: list[tuple[str, ...]] = []
        for i, segment in enumerate(documents[path]):
            words = tuple(WORDS.findall(segment.casefold()))
            shingles = frozenset(words[j : j + size] for j in range(len(words) - size + 1))
            if not shingles:
                if words in short_seen:
                    dropped.add((path, i))
                else:
                    pending_short.append(words)
                continue
            others = sorted({k for s in shingles for k in index.get(s, ())})
            if any(len(shingles & kept[k]) / len(shingles | kept[k]) >= settings.dedup_jaccard for k in others):
                dropped.add((path, i))
            else:
                pending.append(shingles)
        for shingles in pending:
            kept.append(shingles)
            for s in shingles:
                index[s].append(len(kept) - 1)
        short_seen.update(pending_short)
    return dropped
