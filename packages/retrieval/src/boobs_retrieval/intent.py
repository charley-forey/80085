"""Intent normalization -- the first stage of retrieval (spec section 12).

Two agents describing the same job rarely use the same words. Normalizing to
(source format, target format, action) lets an exact-intent match outrank a
merely lexically similar one, which is what makes a paraphrased task find the
right Experience.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

FORMATS: dict[str, tuple[str, ...]] = {
    "pdf": ("pdf",),
    "csv": ("csv", "comma separated"),
    "json": ("json",),
    "xlsx": ("xlsx", "excel", "spreadsheet"),
    "docx": ("docx", "word document"),
    "markdown": ("markdown", "md"),
    "html": ("html", "web page", "webpage"),
    "text": ("plain text", "plaintext", "text"),
    "image": ("image", "png", "jpeg", "jpg", "scan"),
    "yaml": ("yaml", "yml"),
    "xml": ("xml",),
    # "json lines" also matches the bare "json" alias above, inside the same
    # words. _matches drops the reading contained in the longer one, so the
    # more specific label wins -- which is why these compound aliases are safe
    # to list here. (The compound collapse below used to be credited with
    # this and did the opposite: it kept the bare "json".)
    "jsonl": ("jsonl", "ndjson", "json lines", "newline delimited json"),
    "tsv": ("tsv", "tab separated", "tab delimited"),
    "toml": ("toml",),
    "base64": ("base64", "b64"),
    "archive": ("archive", "tarball", "tar", "zip", "gzip"),
}

ACTIONS: dict[str, tuple[str, ...]] = {
    "convert": ("convert", "transform", "turn into", "render", "export", "translate"),
    "extract": ("extract", "parse", "pull out", "scrape", "read", "ocr"),
    "validate": ("validate", "check", "verify", "lint", "conform"),
    "test": ("run tests", "test suite", "pytest", "unit test"),
    "repair": ("repair", "fix", "resolve", "correct"),
    "summarize": ("summarize", "summarise", "condense"),
    "deduplicate": ("deduplicate", "dedupe", "remove duplicate", "drop duplicate"),
    "diff": ("diff", "compare", "difference between"),
    "hash": ("checksum", "sha256", "digest", "hash"),
    "encode": ("encode",),
    "decode": ("decode",),
    "merge": ("merge", "apply patch"),
}

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "can",
        "could",
        "data",
        "document",
        "documents",
        "file",
        "files",
        "for",
        "from",
        "into",
        "my",
        "need",
        "of",
        "or",
        "our",
        "please",
        "should",
        "that",
        "the",
        "this",
        "to",
        "want",
        "we",
        "with",
        "would",
        "you",
    }
)


@dataclass(frozen=True)
class Intent:
    normalized: str
    action: str | None
    source_format: str | None
    target_format: str | None
    keywords: tuple[str, ...] = field(default=())

    @property
    def canonical(self) -> str:
        """Stable intent label, e.g. 'pdf_to_json' or 'validate_json'."""
        if self.source_format and self.target_format:
            return f"{self.source_format}_to_{self.target_format}"
        if self.action and self.source_format:
            return f"{self.action}_{self.source_format}"
        return self.action or "unknown"


# Two format words this close together are one noun phrase, not two formats:
# "spreadsheet-friendly csv" names CSV. But "pdf to json" is also two words
# apart and names two, so a direction word between them blocks the merge.
COMPOUND_WORD_GAP = 2
DIRECTION_WORDS = frozenset({"to", "into", "from", "as", "in"})


def _alias_pattern(alias: str) -> str:
    """An alias, matching however its words are joined in real prose.

    A multi-word alias is written both ways: "newline delimited json" and
    "newline-delimited json" are the same phrase, and the hyphenated spelling
    is the common one. Escaping the alias whole meant only the spaced form
    matched, so "convert to newline-delimited json" normalized to `csv_to_json`
    and every JSONL query was answered with a JSON-array capability.
    """
    return r"\b" + r"[\s\-]+".join(re.escape(word) for word in alias.split()) + r"s?\b"


def _matches(text: str, table: dict[str, tuple[str, ...]]) -> list[tuple[int, str]]:
    """Earliest word-boundary hit per label, as (word index, label), in order.

    Word boundaries matter: a substring search would find "md" inside
    "amd64" and "text" inside "context".

    A label matched *inside* another label's span is the same words counted
    twice -- "json" sits within "newline-delimited json" -- so the shorter
    reading is dropped and the more specific format survives. Without this the
    compound collapse below treated the bare "json" as the head of the phrase
    and threw the JSONL reading away, which is the opposite of what the
    comment on FORMATS promises.
    """
    word_at: dict[int, int] = {}
    offset = 0
    for index, word in enumerate(text.split()):
        word_at[offset] = index
        offset += len(word) + 1

    spans: list[tuple[int, int, str]] = []
    for label, aliases in table.items():
        found = [match for alias in aliases if (match := re.search(_alias_pattern(alias), text))]
        if found:
            # Earliest mention, and the longest reading of it.
            best = min(found, key=lambda match: (match.start(), -(match.end() - match.start())))
            spans.append((best.start(), best.end(), label))

    hits = [
        (word_at.get(start, start), label)
        for start, end, label in spans
        if not any(
            other_start <= start and end <= other_end and other_end - other_start > end - start
            for other_start, other_end, _ in spans
        )
    ]
    return sorted(hits)


def _collapse_compounds(hits: list[tuple[int, str]], words: list[str]) -> list[tuple[int, str]]:
    """Keep the head noun when two format words sit inside one phrase.

    "export json records as a spreadsheet-friendly csv" mentions three formats
    but names two: the CSV is what is produced and "spreadsheet" describes it.
    Without this the target reads as XLSX, the intent becomes json_to_xlsx,
    and the query finds the wrong direction of conversion.
    """
    collapsed: list[tuple[int, str]] = []
    for hit in hits:
        if collapsed:
            previous = collapsed[-1][0]
            between = set(words[previous + 1 : hit[0]])
            if hit[0] - previous <= COMPOUND_WORD_GAP and not (between & DIRECTION_WORDS):
                collapsed[-1] = hit  # the later word is the head of the phrase
                continue
        collapsed.append(hit)
    return collapsed


UNKNOWN = "unknown"


def canonical_label(label: str) -> str:
    """Put a recorded intent label into the namespace queries are normalized to.

    A recorder may name the job whatever it likes, and it does: the corpus
    declares `csv_validate` and `json_diff` while `normalize` emits
    `validate_csv` and `diff_json`. Same concept, opposite word order, and the
    comparison is literal -- so the intent bonus, which exists so a paraphrase
    finds the right Experience, was dead for twenty-three of thirty
    capabilities. Reading both sides through the same normalizer revives it
    without touching a single stored row.

    Idempotent on anything `normalize` produces, which is what a label recorded
    without an explicit intent already is.
    """
    return normalize(label.replace("_", " ")).canonical


def normalize(task: str) -> Intent:
    text = re.sub(r"[^a-z0-9\s\-/.]+", " ", task.lower())
    text = re.sub(r"\s+", " ", text).strip()

    words = text.split()
    format_hits = _collapse_compounds(_matches(text, FORMATS), words)
    action_hits = _matches(text, ACTIONS)

    source = format_hits[0][1] if format_hits else None
    target = format_hits[1][1] if len(format_hits) > 1 else None
    action = action_hits[0][1] if action_hits else None

    # "extract JSON from PDF" names the target first. A "from" sitting between
    # the two formats means the later one is really the source.
    if source and target:
        separator = next((i for i, word in enumerate(words) if word == "from"), None)
        if separator is not None and format_hits[0][0] < separator < format_hits[1][0]:
            source, target = target, source

    keywords = tuple(word for word in text.split() if word not in STOPWORDS and len(word) > 2)
    return Intent(
        normalized=" ".join(keywords),
        action=action,
        source_format=source,
        target_format=target,
        keywords=keywords,
    )
