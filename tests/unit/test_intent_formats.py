"""The vocabulary has to cover the corpus, or exact-intent matching is dead weight.

`FORMATS` knew eleven formats and `ACTIONS` six verbs, which covered three
CSV/JSON examples. A capability the tables cannot name gets no intent match and
falls back to lexical overlap alone -- so it competes on shared words with
every other capability that happens to say "json".
"""

from __future__ import annotations

import pytest

from boobs_retrieval.intent import normalize


@pytest.mark.parametrize(
    ("task", "canonical"),
    [
        ("convert json lines to csv", "jsonl_to_csv"),
        ("ndjson to csv", "jsonl_to_csv"),
        ("turn a tab separated file into json", "tsv_to_json"),
        ("convert toml to json", "toml_to_json"),
        ("convert xml to json", "xml_to_json"),
    ],
)
def test_the_new_formats_are_named(task: str, canonical: str) -> None:
    assert normalize(task).canonical == canonical


def test_json_lines_is_not_read_as_json() -> None:
    """The alias overlaps the bare "json" one at the same word.

    Both match at the same position; _collapse_compounds keeps the head of the
    phrase, so the longer label wins. If that ever stopped being true, every
    JSONL capability would silently answer to plain JSON queries -- which is
    the wrong direction of conversion, not a slightly worse match.
    """
    assert normalize("convert json lines to csv").source_format == "jsonl"
    assert normalize("convert json to csv").source_format == "json"


def test_a_plain_json_task_is_unaffected() -> None:
    """The regression that matters: the old vocabulary still behaves."""
    assert normalize("convert json to csv").canonical == "json_to_csv"
    assert normalize("convert csv to json").canonical == "csv_to_json"


@pytest.mark.parametrize(
    ("task", "action"),
    [
        ("remove duplicate rows from a csv", "deduplicate"),
        ("sha256 checksum of this file", "hash"),
        ("decode this base64 blob", "decode"),
        ("encode the file as base64", "encode"),
        ("compare two json documents", "diff"),
    ],
)
def test_the_new_actions_are_named(task: str, action: str) -> None:
    assert normalize(task).action == action
