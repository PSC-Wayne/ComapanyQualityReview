from types import SimpleNamespace

from company_quality.company_analysis.detailed_analysis import _Row


def test_q2_nine_column_income_row_separates_single_quarter_and_ytd() -> None:
    row = _Row(
        artifact=SimpleNamespace(),
        label="營業收入合計",
        cells=(
            "營業收入合計",
            "933,791,869",
            "100.00",
            "673,510,177",
            "100.00",
            "1,773,045,533",
            "100.00",
            "1,266,154,378",
            "100.00",
        ),
        evidence_id="evidence:q2-revenue",
    )

    assert row.current == 933_791_869
    assert row.prior == 673_510_177
    assert row.current_percent == 100
    assert row.prior_percent == 100
    assert row.ytd_current == 1_773_045_533
    assert row.ytd_prior == 1_266_154_378
