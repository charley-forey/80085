"""Package marker.

Without one, pytest imports `tests/unit/test_lineage.py` and
`tests/integration/test_lineage.py` as the same top-level module `test_lineage`
and refuses to collect the second. CI runs the directories separately and
never saw it; `make test` runs them together and could not collect at all.
"""
