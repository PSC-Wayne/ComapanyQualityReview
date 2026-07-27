from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from company_quality.lab.historical_legal_identity import (
    resolve_historical_legal_identities,
)


def _universe() -> pd.DataFrame:
    return pd.DataFrame([
        {"decision_date": "2024-06-30", "market": "TWSE", "security_code": "2330", "company_name": "台積電"},
        {"decision_date": "2024-06-30", "market": "TWSE", "security_code": "2358", "company_name": "廷鑫"},
        {"decision_date": "2022-06-30", "market": "TPEx", "security_code": "1258", "company_name": "其祥-KY"},
        {"decision_date": "2019-06-30", "market": "TPEx", "security_code": "1333", "company_name": "恩得利"},
    ])


def test_resolves_current_and_historical_domestic_and_separates_foreign() -> None:
    filing_calls: list[tuple[str, tuple[int, ...]]] = []
    registry_calls: list[tuple[str, str]] = []

    def filing(code: str, years: tuple[int, ...]) -> tuple[str, str] | None:
        filing_calls.append((code, years))
        if code == "2358":
            return "廷鑫興業股份有限公司", "https://mopsov.twse.com.tw/pre-oos-2358"
        return None

    def registry(code: str, name: str) -> dict[str, object] | None:
        registry_calls.append((code, name))
        return {
            "Business_Accounting_NO": "22423848",
            "Company_Name": name,
            "_identity_link_source": "https://data.gcis.nat.gov.tw/2358",
        }

    frame, report = resolve_historical_legal_identities(
        _universe(),
        twse_current=[{
            "公司代號": "2330",
            "公司名稱": "台灣積體電路製造股份有限公司",
            "營利事業統一編號": "22099131",
        }],
        tpex_current=[],
        final_oos_start=date(2025, 1, 1),
        fetch_filing=filing,
        fetch_registry=registry,
    )

    rows = frame.set_index("security_code")
    assert rows.loc["2330", "identity_status"] == "CURRENT_OFFICIAL_UBN"
    assert rows.loc["2330", "unified_business_number"] == "22099131"
    assert rows.loc["2358", "identity_status"] == "PRE_OOS_FILING_GCIS_UBN"
    assert rows.loc["2358", "unified_business_number"] == "22423848"
    assert rows.loc["1258", "identity_status"] == "FOREIGN_ISSUER_NO_TAIWAN_UBN"
    assert rows.loc["1333", "identity_status"] == "MISSING_PRE_OOS_FILING_IDENTITY"
    assert filing_calls == [
        ("1333", (2018, 2017, 2016, 2015)),
        ("2358", (2023, 2022, 2021, 2020)),
    ]
    assert registry_calls == [("2358", "廷鑫興業股份有限公司")]
    assert report == {
        "schema_version": "HistoricalLegalIdentityResolution.v1",
        "status": "BLOCKED_DOMESTIC_IDENTITY_GAPS",
        "final_oos_start": "2025-01-01",
        "security_code_count": 4,
        "resolved_ubn_count": 2,
        "foreign_issuer_count": 1,
        "domestic_identity_gap_count": 1,
        "status_counts": {
            "CURRENT_OFFICIAL_UBN": 1,
            "FOREIGN_ISSUER_NO_TAIWAN_UBN": 1,
            "MISSING_PRE_OOS_FILING_IDENTITY": 1,
            "PRE_OOS_FILING_GCIS_UBN": 1,
        },
        "membership_source": "OfficialTradingUniverse.v1",
        "current_company_api_usage": "immutable_identity_metadata_only",
        "foreign_identity_policy": "separate_without_fabricated_taiwan_ubn",
        "final_oos_rows_read": False,
    }


def test_refuses_universe_touching_final_oos_before_fetch() -> None:
    universe = _universe()
    universe.loc[0, "decision_date"] = "2025-01-01"

    def forbidden(*_: object) -> None:
        raise AssertionError("fetch must not run")

    with pytest.raises(ValueError, match="universe decision dates must precede final OOS"):
        resolve_historical_legal_identities(
            universe,
            twse_current=[],
            tpex_current=[],
            final_oos_start=date(2025, 1, 1),
            fetch_filing=forbidden,
            fetch_registry=forbidden,
        )
