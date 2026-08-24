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


def test_a_recorded_label_is_read_in_the_same_namespace_as_a_query() -> None:
    """The corpus declares `csv_validate`; `normalize` emits `validate_csv`.

    The comparison is literal, so the intent bonus -- the whole mechanism for
    letting a paraphrase find the right Experience -- was dead for twenty-three
    of thirty capabilities. Both sides go through the normalizer now.
    """
    from boobs_retrieval.intent import canonical_label

    assert canonical_label("csv_validate") == normalize("validate a CSV file").canonical
    assert canonical_label("json_diff") == normalize("diff two json documents").canonical
    assert canonical_label("archive_extract") == normalize("extract a tarball").canonical

    # Idempotent on whatever normalize itself produced, which is what a label
    # recorded without an explicit intent already is.
    for label in ("csv_to_json", "validate_csv", "extract", "unknown"):
        assert canonical_label(label) == label

    # A label the normalizer cannot read stays unreadable rather than becoming
    # a wildcard that matches every other unreadable one.
    assert canonical_label("business_day_arithmetic") == "unknown"


def test_unpacking_an_archive_is_extracting_it() -> None:
    """ "unpack a tarball" named no action, so the query fell back to `unknown`,
    no intent bonus reached the extractor, and in production the archive
    *creator* came back above it -- both scored low enough to read `avoid`."""
    from boobs_retrieval.intent import canonical_label

    assert normalize("unpack a tarball").canonical == "extract_archive"
    assert normalize("untar this archive").canonical == "extract_archive"
    assert normalize("unpack a tarball").canonical == canonical_label("archive_extract")

    # "zip" hides inside "unzip"; a word-boundary search must not read the
    # verb as the format it operates on.
    assert normalize("unzip the file").source_format is None
