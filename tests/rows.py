"""
Comparing warehouse rows as frames.

The layers pass rows as list[dict], and a failed comparison of those reads
as one long diff. Going through pandas reports which column of which row
differs, which is what you want when a row has sixteen columns.
"""

import pandas as pd
from pandas.testing import assert_frame_equal


def assert_rows_equal(actual: list[dict], expected: list[dict]) -> None:
    """Fails with a column-by-column diff when the rows differ."""
    assert_frame_equal(
        pd.DataFrame(actual),
        pd.DataFrame(expected),
        check_like=True,  # column order is not part of the contract
    )


def assert_no_rows(actual: list[dict]) -> None:
    """An empty write, which must still be a write."""
    assert_rows_equal(actual, [])
