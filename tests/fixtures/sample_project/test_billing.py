# Fixture file: test_billing.py
#
# This file matches ``test_*.py`` and is skipped entirely by the walker, so it
# contributes nothing to either output file.
#
# (no EXPECTED-INCLUDE entries)
# (no EXPECTED-EXCLUDE entries)

from billing import compute_total


def test_compute_total_is_positive() -> None:
    assert compute_total([2.0], 0.0) > 0


def helper_not_reached() -> None:
    return None
