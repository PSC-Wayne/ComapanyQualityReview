from datetime import date
from pathlib import Path

import pandas as pd

import company_quality.lab.finlab_materializer as materializer
from company_quality.lab.finlab_materializer import (
    ADJUSTED_PRICE_DATASET,
    PRICE_DATASET,
    SECURITY_CATEGORIES_DATASET,
    VOLUME_DATASET,
    materialize_finlab,
)


def test_mopsov_filing_identity_binds_stock_code_to_legal_name(monkeypatch):
    body = (
        '<ix:nonNumeric name="tifrs-notes:CompanyID">2456</ix:nonNumeric>'
        '<ix:nonNumeric name="tifrs-notes:CompanyChineseName">'
        '奇力新電子股份有限公司</ix:nonNumeric>'
    ).encode("big5")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return body

    monkeypatch.setattr(materializer, "urlopen", lambda *_args, **_kwargs: Response())
    result = materializer._fetch_mopsov_filing_identity(
        "2456", range(2020, 2019, -1)
    )
    assert result is not None
    name, source = result
    assert name == "奇力新電子股份有限公司"
    assert "CO_ID=2456" in source


def test_finlab_materializer_filters_company_stocks_and_normalizes_wealth(
    tmp_path: Path,
) -> None:
    index = pd.to_datetime(["2025-01-02", "2025-01-03"])
    categories = pd.DataFrame([
        {"stock_id": "1101", "name": "台泥", "market": "sii", "category": "水泥"},
        {"stock_id": "6488", "name": "環球晶", "market": "otc", "category": "半導體"},
        {"stock_id": "0050", "name": "ETF", "market": "other_securities", "category": "ETF"},
    ])
    frames = {
        SECURITY_CATEGORIES_DATASET: categories,
        PRICE_DATASET: pd.DataFrame(
            {"1101": [40.0, 41.0], "6488": [300.0, 303.0], "0050": [50.0, 51.0]},
            index=index,
        ),
        ADJUSTED_PRICE_DATASET: pd.DataFrame(
            {"1101": [20.0, 21.0], "6488": [100.0, 101.0], "0050": [25.0, 25.5]},
            index=index,
        ),
        VOLUME_DATASET: pd.DataFrame(
            {"1101": [1000, 2000], "6488": [3000, 4000], "0050": [5000, 6000]},
            index=index,
        ),
    }

    report = materialize_finlab(
        data_get=frames.__getitem__,
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        output_dir=tmp_path,
        official_identity_payloads={
            "twse_current": [{
                "公司代號": "1101",
                "公司名稱": "臺灣水泥股份有限公司",
                "營利事業統一編號": "11913502",
                "上市日期": "19620209",
            }],
            "tpex_current": [{
                "SecuritiesCompanyCode": "6488",
                "CompanyName": "環球晶圓股份有限公司",
                "UnifiedBusinessNo.": "28113286",
                "DateOfListing": "20150925",
            }],
            "twse_public": [],
            "mops_profiles": [],
            "gcis_identities": [],
            "twse_delisted": {
                "fields": ["終止上市日期", "公司名稱", "上市編號"],
                "data": [],
            },
            "tpex_delisted": [],
        },
    )

    assert report["security_count"] == 2
    assert report["market_security_counts"] == {"otc": 1, "sii": 1}
    assert report["ready_security_count"] == 2
    wealth = pd.read_parquet(tmp_path / "adjusted_wealth.parquet")
    assert wealth.loc[index[0], "1101"] == 100
    assert wealth.loc[index[1], "1101"] == 105
    assert "0050" not in wealth.columns
    identity_report = report["official_identity"]
    assert isinstance(identity_report, dict)
    assert identity_report["security_membership_coverage"] == 1
    assert identity_report["legal_identity_coverage"] == 1


def test_finlab_materializer_keeps_delisted_lifecycle_separate_from_legal_identity(
    tmp_path: Path,
) -> None:
    index = pd.to_datetime(["2025-01-02"])
    categories = pd.DataFrame([
        {"stock_id": "6806", "name": "森崴能源", "market": "sii", "category": "綠能"},
        {"stock_id": "1258", "name": "其祥-KY", "market": "otc", "category": "食品"},
    ])
    frames = {
        SECURITY_CATEGORIES_DATASET: categories,
        PRICE_DATASET: pd.DataFrame({"6806": [100], "1258": [20]}, index=index),
        ADJUSTED_PRICE_DATASET: pd.DataFrame({"6806": [100], "1258": [20]}, index=index),
        VOLUME_DATASET: pd.DataFrame({"6806": [1000], "1258": [1000]}, index=index),
    }
    report = materialize_finlab(
        data_get=frames.__getitem__,
        start=date(2025, 1, 2),
        end=date(2025, 1, 2),
        output_dir=tmp_path,
        official_identity_payloads={
            "twse_current": [],
            "tpex_current": [],
            "twse_public": [{
                "公司代號": "6806",
                "公司名稱": "森崴能源股份有限公司",
                "營利事業統一編號": "28653781",
                "上市日期": "20200930",
            }],
            "mops_profiles": [{
                "stockId": "6806",
                "companyName": "森崴能源股份有限公司",
                "businessNo": "28653781",
                "listingDate": "110/11/15",
            }],
            "gcis_identities": [],
            "twse_delisted": {
                "fields": ["終止上市日期", "公司名稱", "上市編號"],
                "data": [["115/06/23", "森崴能源", "6806"]],
            },
            "tpex_delisted": [{
                "tables": [{
                    "fields": [
                        "股票代號", "公司名稱", "終止上櫃日期",
                        "終止上櫃原因", "公司資料網址",
                    ],
                    "data": [[
                        "1258", "其祥生物科技控股股份有限公司", "110-12-15",
                        "官方終止上櫃原因", "https://mops.twse.com.tw/",
                    ]],
                }],
            }],
        },
    )
    identity = pd.read_parquet(tmp_path / "official_identity.parquet")
    twse = identity.loc[identity["security_code"] == "6806"].iloc[0]
    otc = identity.loc[identity["security_code"] == "1258"].iloc[0]
    assert twse["identity_status"] == "OFFICIAL_DELISTED_LEGAL_IDENTITY"
    assert twse["security_lifecycle_id"] == "sii:6806:delisted:115/06/23"
    assert bool(twse["legal_identity_resolved"])
    assert twse["unified_business_number"] == "28653781"
    assert twse["listed_on"] == "110/11/15"
    assert twse["public_on"] == "20200930"
    assert otc["identity_status"] == "UNRESOLVED_FOREIGN_LEGAL_IDENTITY"
    assert otc["security_lifecycle_id"] == "otc:1258:delisted:110-12-15"
    assert not bool(otc["legal_identity_resolved"])
    identity_report = report["official_identity"]
    assert isinstance(identity_report, dict)
    assert identity_report["security_membership_resolved_count"] == 2
    assert identity_report["legal_identity_gap_count"] == 1
    assert identity_report["t20_status"] == "BLOCKED_INCOMPLETE_LEGAL_IDENTITY"
