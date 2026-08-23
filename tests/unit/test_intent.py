"""Intent normalization is what lets a paraphrased task find the right
Experience, so it gets tested on the paraphrases people actually write."""

from __future__ import annotations

import pytest

from boobs_retrieval.intent import normalize


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("Convert a CSV file into JSON", "csv_to_json"),
        ("turn my csv into json please", "csv_to_json"),
        ("extract JSON from a PDF invoice", "pdf_to_json"),
        ("Convert invoice PDFs into normalized JSON", "pdf_to_json"),
        ("render markdown to pdf", "markdown_to_pdf"),
        ("validate this json document", "validate_json"),
        # A format word can modify another format word rather than name a
        # second format: this is CSV output, not XLSX output.
        ("export json records as a spreadsheet-friendly csv", "json_to_csv"),
        ("convert an excel spreadsheet to csv", "xlsx_to_csv"),
        ("Convert invoice PDFs into normalized JSON", "pdf_to_json"),
        ("Convert a JSON array of objects into a CSV file", "json_to_csv"),
    ],
)
def test_canonical_intent(task: str, expected: str) -> None:
    assert normalize(task).canonical == expected


def test_from_reverses_source_and_target() -> None:
    forward = normalize("convert pdf to json")
    reverse = normalize("extract json from pdf")
    assert forward.canonical == reverse.canonical == "pdf_to_json"


def test_word_boundaries_not_substrings() -> None:
    """'amd64' contains 'md' and 'context' contains 'text'; neither is a format."""
    intent = normalize("run the tests on amd64 in this context")
    assert intent.source_format is None
    assert intent.target_format is None


def test_keywords_drop_filler() -> None:
    intent = normalize("please can you convert the CSV file into JSON for me")
    assert "the" not in intent.keywords
    assert "file" not in intent.keywords
    assert "convert" in intent.keywords


def test_compound_format_words_do_not_swallow_a_real_direction() -> None:
    """The compound rule must not merge "pdf to json" into a single format."""
    assert normalize("convert pdf to json").canonical == "pdf_to_json"
    assert normalize("render markdown to pdf").canonical == "markdown_to_pdf"
