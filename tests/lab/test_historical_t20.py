from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pandas as pd

from company_quality.lab.official_benchmarks import TWSE_TOTAL_RETURN_URL
import company_quality.lab.real_t21 as real_t21
from company_quality.lab.historical_t20 import build_historical_t20


def _universe() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "decision_date": "2017-06-30",
            "market": "TWSE",
            "security_code": "1101",
            "company_name": "台泥",
            "source_ref": "https://www.twse.com.tw/official",
        },
        {
            "decision_date": "2018-06-30",
            "market": "TWSE",
            "security_code": "1101",
            "company_name": "台泥",
            "source_ref": "https://www.twse.com.tw/official",
        },
        {
            "decision_date": "2017-06-30",
            "market": "TPEx",
            "security_code": "1258",
            "company_name": "其祥-KY",
            "source_ref": "https://www.tpex.org.tw/official",
        },
        {
            "decision_date": "2017-06-30",
            "market": "TPEx",
            "security_code": "9998",
            "company_name": "缺口",
            "source_ref": "https://www.tpex.org.tw/official",
        },
    ])


def _identity() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "security_code": "1101",
            "official_name": "臺灣水泥股份有限公司",
            "unified_business_number": "11913502",
            "identity_status": "CURRENT_OFFICIAL_UBN",
            "identity_source_ref": "https://openapi.twse.com.tw/identity",
        },
        {
            "security_code": "1258",
            "official_name": "其祥生物科技控股股份有限公司",
            "unified_business_number": None,
            "identity_status": "FOREIGN_ISSUER_NO_TAIWAN_UBN",
            "identity_source_ref": None,
        },
        {
            "security_code": "9998",
            "official_name": "缺口股份有限公司",
            "unified_business_number": None,
            "identity_status": "GCIS_IDENTITY_UNRESOLVED",
            "identity_source_ref": None,
        },
    ])


def test_historical_t20_records_owner_exclusions_without_fake_listing_dates() -> None:
    payload = build_historical_t20(_universe(), _identity())

    cohorts = cast(dict[str, dict[str, object]], payload["cohorts"])
    twse = cohorts["TWSE"]
    assert twse["issuer_ids"] == ["11913502"]
    assert twse["members"] == [{
        "issuer_id": "11913502",
        "security_code": "1101",
        "company_name": "臺灣水泥股份有限公司",
        "market": "TWSE",
        "observed_decision_dates": ["2017-06-30", "2018-06-30"],
        "evidence_ids": [
            "https://www.twse.com.tw/official",
            "https://openapi.twse.com.tw/identity",
        ],
    }]
    members = cast(list[dict[str, object]], twse["members"])
    assert "listed_on" not in members[0]
    failures = cast(
        dict[str, dict[str, str]], payload["pre_admission_failures"]
    )["TPEx"]
    assert failures == {
        "security:TPEx:1258": "owner_excluded_foreign_issuer",
        "security:TPEx:9998": "unresolved_immutable_legal_identity",
    }
    assert payload["final_oos_rows_read"] is False


def test_real_t21_uses_exact_quote_observed_decision_membership(monkeypatch) -> None:
    payload = build_historical_t20(_universe().iloc[:1], _identity().iloc[:1])

    def fake_label(*_args, **kwargs):
        decision = str(kwargs["decision_time"])[:10]
        year = int(decision[:4])
        return SimpleNamespace(
            twelve_month_return=SimpleNamespace(
                result_end_date=f"{year + 1}-06-30",
                actual_total_return=Decimal("0.10"),
                official_benchmark_return=Decimal("0.05"),
                official_excess_return=Decimal("0.05"),
                positive_return=True,
                outperformed_official_market=True,
                status="fully_observed",
                official_benchmark_source_ref=TWSE_TOTAL_RETURN_URL,
            ),
            drawdown_episodes=(),
            adverse_labels=(),
            censoring_state="fully_observed",
            label_coverage=Decimal("1"),
            available_at=f"{year + 1}-07-01T00:00:00+08:00",
            formula_version="test",
            generation_id=payload["generation_id"],
        )

    monkeypatch.setattr(real_t21, "build_outcome_label_set", fake_label)
    dates = pd.to_datetime(["2016-06-30", "2017-06-30", "2018-06-30"])
    labels, report = real_t21.build_real_t21(
        payload,
        pd.DataFrame({"1101": [90.0, 100.0, 110.0]}, index=dates),
        _identity().iloc[:1],
        {"materialized_at": "2019-01-01T00:00:00+00:00"},
        {
            "TWSE": pd.Series([100.0, 105.0], index=dates[:2]),
            "TPEx": pd.Series([100.0, 105.0], index=dates[:2]),
        },
        _universe().iloc[:1],
        decision_dates=("2017-06-30", "2018-06-30"),
        source_root=Path(real_t21.__file__).parents[1],
    )

    assert labels["decision_date"].tolist() == ["2017-06-30"]
    assert report["attempted_label_count"] == 1
