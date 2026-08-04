import pandas as pd
import pytest

from company_quality.lab.real_features import _column


def test_column_stitches_non_overlapping_security_name_aliases() -> None:
    frame = pd.DataFrame(
        {
            "2204 中華汽車": [100.0, 110.0, None, None],
            "2204 中華": [None, None, 120.0, 130.0],
        },
        index=pd.date_range("2020-01-01", periods=4, freq="MS"),
    )

    result = _column(frame, "2204")

    assert result.tolist() == [100.0, 110.0, 120.0, 130.0]
    assert result.index.tolist() == frame.index.tolist()


def test_column_accepts_equal_overlap_but_blocks_conflicting_alias_values() -> None:
    index = pd.date_range("2020-01-01", periods=2, freq="MS")
    equal = pd.DataFrame(
        {"2204 old": [100.0, None], "2204 new": [100.0, 110.0]}, index=index
    )
    assert _column(equal, "2204").tolist() == [100.0, 110.0]

    conflicting = pd.DataFrame(
        {"2204 old": [100.0, None], "2204 new": [101.0, 110.0]}, index=index
    )
    with pytest.raises(ValueError, match="conflicting alias values for security 2204"):
        _column(conflicting, "2204")


def test_column_preserves_datetime_index_type_when_security_is_missing() -> None:
    frame = pd.DataFrame(
        {"2330": [100.0]}, index=pd.DatetimeIndex(["2020-01-01"])
    )

    result = _column(frame, "5280")

    assert result.empty
    assert isinstance(result.index, pd.DatetimeIndex)
