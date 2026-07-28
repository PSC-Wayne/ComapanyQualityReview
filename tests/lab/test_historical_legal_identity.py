from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
import requests

from company_quality.lab.historical_legal_identity import (
    _live_document_filing,
    _live_filing,
    _live_mopsov_filing,
    _live_pre_oos_event_name,
    _live_trading_registry,
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
        "source_unavailable_count": 0,
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


def test_live_filing_reads_official_financial_report_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __init__(self, status: int, *, text: str = "", content: bytes = b"") -> None:
            self.status_code = status
            self.text = text
            self.content = content

    class Session:
        def __init__(self) -> None:
            self.post_calls = 0

        def get(self, _url: str, **kwargs: object) -> Response:
            if "params" in kwargs:
                return Response(
                    200,
                    text=r'readfile2(\"A\",\"1724\",\"202004_1724_AI1.pdf\")',
                )
            return Response(200, content=b"%PDF-fake")

        def post(self, _url: str, **_kwargs: object) -> Response:
            self.post_calls += 1
            if self.post_calls == 1:
                raise requests.ConnectionError("transient")
            return Response(200, text="<a href='/pdf/report.pdf'>report</a>")

    class Page:
        def extract_text(self) -> str:
            return "台硝股份有限公司及子公司\n民國109年度\n(股票代碼1724)"

    class Reader:
        pages = [Page()]

    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.requests.Session",
        Session,
    )
    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.PdfReader",
        lambda _stream: Reader(),
    )
    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.time.sleep",
        lambda _seconds: None,
    )

    assert _live_document_filing("1724", (2020,)) == (
        "台硝股份有限公司",
        "https://doc.twse.com.tw/server-java/t57sb01?"
        "step=1&colorchg=1&seamon=&mtype=A&co_id=1724&year=109#"
        "202004_1724_AI1.pdf",
    )


def test_live_filing_fails_on_document_index_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 503
        text = ""

    class Session:
        def get(self, _url: str, **_kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.requests.Session",
        Session,
    )

    with pytest.raises(RuntimeError, match="document index failed: HTTP 503"):
        _live_document_filing("1724", (2020,))


def test_live_filing_keeps_scanned_pdf_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 200
        text = r'readfile2(\"A\",\"1566\",\"201804_1566_AI1.pdf\")'
        content = b"%PDF-fake"

    class Session:
        def get(self, _url: str, **_kwargs: object) -> Response:
            return Response()

        def post(self, _url: str, **_kwargs: object) -> Response:
            response = Response()
            response.text = "<a href='/pdf/report.pdf'>report</a>"
            return response

    class Page:
        def extract_text(self) -> str:
            return ""

    class Reader:
        pages = [Page()]

    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.requests.Session", Session
    )
    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.PdfReader",
        lambda _stream: Reader(),
    )

    assert _live_document_filing("1566", (2018,)) is None


def test_live_filing_uses_document_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def mops(_code: str, _years: tuple[int, ...]) -> None:
        calls.append("mopsov")
        return None

    def document(_code: str, _years: tuple[int, ...]) -> tuple[str, str]:
        calls.append("document")
        return "台硝股份有限公司", "https://doc.twse.com.tw/report"

    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity._live_mopsov_filing", mops
    )
    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity._live_document_filing",
        document,
    )

    assert _live_filing("1724", (2020,)) == (
        "台硝股份有限公司",
        "https://doc.twse.com.tw/report",
    )
    assert calls == ["mopsov", "document"]


def test_mopsov_filing_removes_group_scope_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 200
        url = "https://mopsov.twse.com.tw/4944"
        content = (
            'name="tifrs-notes:CompanyID">4944<'
            'name="tifrs-notes:CompanyChineseName">兆遠科技股份有限公司及子公司<'
        ).encode("big5")

    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.requests.get",
        lambda *_args, **_kwargs: Response(),
    )
    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.time.sleep",
        lambda _seconds: None,
    )

    assert _live_mopsov_filing("4944", (2022,)) == (
        "兆遠科技股份有限公司",
        "https://mopsov.twse.com.tw/4944",
    )


def test_mopsov_filing_falls_back_from_c_to_a(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Response:
        status_code = 200
        url = "https://mopsov.twse.com.tw/1566"

        def __init__(self, report_id: str) -> None:
            self.content = (
                (
                    'name="tifrs-notes:CompanyID">1566<'
                    'name="tifrs-notes:CompanyChineseName">捷邦精密股份有限公司<'
                ).encode("big5")
                if report_id == "A"
                else b"no filing"
            )

    def get(*_args: object, **kwargs: object) -> Response:
        params = kwargs["params"]
        assert isinstance(params, dict)
        report_id = str(params["REPORT_ID"])
        calls.append(report_id)
        return Response(report_id)

    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.requests.get", get
    )
    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.time.sleep",
        lambda _seconds: None,
    )

    assert _live_mopsov_filing("1566", (2018,)) == (
        "捷邦精密股份有限公司",
        "https://mopsov.twse.com.tw/1566",
    )
    assert calls == ["C", "A"]


def test_resolves_unique_legal_name_matching_official_trading_name() -> None:
    universe = pd.DataFrame([{
        "decision_date": "2019-06-30",
        "market": "TPEx",
        "security_code": "1566",
        "company_name": "捷邦",
        "source_ref": "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",
    }])

    frame, report = resolve_historical_legal_identities(
        universe,
        twse_current=[],
        tpex_current=[],
        final_oos_start=date(2025, 1, 1),
        fetch_filing=lambda _code, _years: None,
        fetch_registry=lambda _code, _name: None,
        fetch_trading_registry=lambda _code, _name: {
            "Business_Accounting_NO": "12503674",
            "Company_Name": "捷邦股份有限公司",
            "_identity_link_source": "https://data.gcis.nat.gov.tw/1566",
        },
    )

    row = frame.iloc[0]
    assert row["official_name"] == "捷邦股份有限公司"
    assert row["unified_business_number"] == "12503674"
    assert row["identity_status"] == "OFFICIAL_TRADING_NAME_GCIS_UBN"
    assert row["filing_source_ref"] == universe.loc[0, "source_ref"]
    assert row["identity_source_ref"] == "https://data.gcis.nat.gov.tw/1566"
    assert report["resolved_ubn_count"] == 1


def test_trading_name_registry_rejects_two_distinct_ubns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 200

        def __init__(self, status: str) -> None:
            self.url = f"https://data.gcis.nat.gov.tw/status/{status}"
            self.content = b"[]"
            self._status = status

        def json(self) -> list[dict[str, object]]:
            if self._status not in {"01", "04"}:
                return []
            return [{
                "Business_Accounting_NO": (
                    "22248651" if self._status == "01" else "22203367"
                ),
                "Company_Name": "連展科技股份有限公司",
            }]

    def get(*_args: object, **kwargs: object) -> Response:
        params = kwargs["params"]
        assert isinstance(params, dict)
        status = str(params["$filter"]).rsplit(" ", 1)[-1]
        return Response(status)

    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.requests.get", get
    )

    assert _live_trading_registry("5491", "連展科技") is None


def test_resolves_pre_oos_rename_event_to_unique_current_ubn() -> None:
    universe = pd.DataFrame([{
        "decision_date": "2023-06-30",
        "market": "TPEx",
        "security_code": "4712",
        "company_name": "南璋",
        "source_ref": "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",
    }])
    registry_calls: list[str] = []

    def registry(_code: str, name: str) -> dict[str, object] | None:
        registry_calls.append(name)
        if name != "福格創新股份有限公司":
            return None
        return {
            "Business_Accounting_NO": "43696296",
            "Company_Name": name,
            "_identity_link_source": "https://data.gcis.nat.gov.tw/4712",
        }

    frame, report = resolve_historical_legal_identities(
        universe,
        twse_current=[],
        tpex_current=[],
        final_oos_start=date(2025, 1, 1),
        fetch_filing=lambda _code, _years: (
            "南璋股份有限公司", "https://mopsov.twse.com.tw/4712"
        ),
        fetch_registry=registry,
        fetch_pre_oos_event_name=lambda *_args: (
            "福格創新股份有限公司",
            "南璋股份有限公司",
            "https://mops.twse.com.tw/mops/api/t05st01#4712-112",
        ),
    )

    row = frame.iloc[0]
    assert registry_calls == ["南璋股份有限公司", "福格創新股份有限公司"]
    assert row["official_name"] == "南璋股份有限公司"
    assert row["unified_business_number"] == "43696296"
    assert row["identity_status"] == "PRE_OOS_EVENT_GCIS_UBN"
    assert row["filing_source_ref"].endswith("#4712-112")
    assert row["identity_source_ref"] == "https://data.gcis.nat.gov.tw/4712"
    assert report["resolved_ubn_count"] == 1


def test_pre_oos_event_extracts_exact_official_trading_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"result": {"data": [[
                "6806", "森崴能源", "113/03/05", "14:48:06",
                "公告森崴能源股份有限公司國內第一次有擔保轉換公司債",
            ]]}}

    calls: list[dict[str, object]] = []

    def post(*_args: object, **kwargs: object) -> Response:
        body = kwargs["json"]
        assert isinstance(body, dict)
        calls.append(body)
        return Response()

    monkeypatch.setattr(
        "company_quality.lab.historical_legal_identity.requests.post", post
    )

    result = _live_pre_oos_event_name(
        "6806", ("森崴能源",), "森崴股份有限公司", (2024,)
    )

    assert result is not None
    assert result[0] == "森崴能源股份有限公司"
    assert result[1] == "森崴能源股份有限公司"
    assert calls == [{
        "companyId": "6806", "year": "113", "month": "all",
        "firstDay": "", "lastDay": "",
    }]


def test_resolves_exact_current_identity_name_chain() -> None:
    universe = pd.DataFrame([{
        "decision_date": "2021-06-30",
        "market": "TWSE",
        "security_code": "2823",
        "company_name": "中壽",
        "source_ref": "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
    }])
    registry_calls: list[str] = []

    def registry(_code: str, name: str) -> dict[str, object] | None:
        registry_calls.append(name)
        if name != "凱基人壽保險股份有限公司":
            return None
        return {
            "Business_Accounting_NO": "03434016",
            "Company_Name": name,
            "_identity_link_source": "https://data.gcis.nat.gov.tw/2823",
        }

    frame, report = resolve_historical_legal_identities(
        universe,
        twse_current=[],
        tpex_current=[],
        final_oos_start=date(2025, 1, 1),
        fetch_filing=lambda _code, _years: (
            "中國人壽保險股份有限公司", "https://mopsov.twse.com.tw/2823"
        ),
        fetch_registry=registry,
        fetch_pre_oos_event_name=lambda *_args: None,
        fetch_current_identity_chain=lambda _code: (
            "凱基人壽保險股份有限公司",
            "中國人壽保險股份有限公司",
            "https://mops.twse.com.tw/mops/api/t05st03#companyId=2823",
        ),
    )

    row = frame.iloc[0]
    assert registry_calls == [
        "中國人壽保險股份有限公司", "凱基人壽保險股份有限公司",
    ]
    assert row["official_name"] == "中國人壽保險股份有限公司"
    assert row["unified_business_number"] == "03434016"
    assert row["identity_status"] == "CURRENT_OFFICIAL_IDENTITY_CHAIN_UBN"
    assert row["filing_source_ref"].endswith("#companyId=2823")
    assert row["identity_source_ref"] == "https://data.gcis.nat.gov.tw/2823"
    assert report["resolved_ubn_count"] == 1


def test_source_failure_is_separate_from_confirmed_identity_gap() -> None:
    universe = _universe().query("security_code == '1333'")

    def unavailable(_code: str, _years: tuple[int, ...]) -> None:
        raise requests.ConnectionError("official source disconnected")

    frame, report = resolve_historical_legal_identities(
        universe,
        twse_current=[],
        tpex_current=[],
        final_oos_start=date(2025, 1, 1),
        fetch_filing=unavailable,
        fetch_registry=lambda _code, _name: None,
    )

    assert frame.loc[0, "identity_status"] == "SOURCE_UNAVAILABLE"
    assert frame.loc[0, "source_error"] == (
        "ConnectionError: official source disconnected"
    )
    assert report["source_unavailable_count"] == 1
    assert report["domestic_identity_gap_count"] == 0
    assert report["status"] == "BLOCKED_SOURCE_UNAVAILABLE"


def test_resume_reuses_completed_rows_and_retries_source_unavailable() -> None:
    universe = _universe().query("security_code in ['1333', '2358']")
    resumed = pd.DataFrame([
        {
            "security_code": "1333",
            "markets": '["TPEx"]',
            "observed_names": '["恩得利"]',
            "last_decision_date": "2019-06-30",
            "official_name": None,
            "unified_business_number": None,
            "identity_status": "MISSING_PRE_OOS_FILING_IDENTITY",
            "filing_source_ref": None,
            "identity_source_ref": None,
            "source_error": None,
        },
        {
            "security_code": "2358",
            "markets": '["TWSE"]',
            "observed_names": '["廷鑫"]',
            "last_decision_date": "2024-06-30",
            "official_name": None,
            "unified_business_number": None,
            "identity_status": "SOURCE_UNAVAILABLE",
            "filing_source_ref": None,
            "identity_source_ref": None,
            "source_error": "ConnectionError: old failure",
        },
    ])
    filing_calls: list[str] = []
    checkpointed: list[str] = []

    def filing(code: str, _years: tuple[int, ...]) -> None:
        filing_calls.append(code)
        return None

    frame, _report = resolve_historical_legal_identities(
        universe,
        twse_current=[],
        tpex_current=[],
        final_oos_start=date(2025, 1, 1),
        fetch_filing=filing,
        fetch_registry=lambda _code, _name: None,
        resume_records=resumed,
        record_callback=lambda row: checkpointed.append(str(row["security_code"])),
    )

    assert filing_calls == ["2358"]
    assert checkpointed == ["2358"]
    assert frame.set_index("security_code").loc["1333", "identity_status"] == (
        "MISSING_PRE_OOS_FILING_IDENTITY"
    )
    assert frame.set_index("security_code").loc["2358", "identity_status"] == (
        "MISSING_PRE_OOS_FILING_IDENTITY"
    )
