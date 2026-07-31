from decimal import Decimal

import pytest

from company_quality.filing_store import FilingStore
from company_quality.sources.monthly_revenue import (
    MonthlyRevenueError,
    MopsMonthlyRevenueCollector,
    RevenueMonth,
    trailing_months,
)


HTML = """<html><body>
本資料由 (上市公司)台積電 公司提供
民國115年06月
<table>
<tr><th>項目</th><th>營業收入淨額</th></tr>
<tr><td>本月</td><td>442,679,969</td></tr>
<tr><td>去年同期</td><td>263,708,978</td></tr>
<tr><td>增減金額</td><td>178,970,991</td></tr>
<tr><td>增減百分比</td><td>67.87</td></tr>
<tr><td>本年累計</td><td>2,404,483,690</td></tr>
<tr><td>去年累計</td><td>1,773,045,533</td></tr>
<tr><td>增減金額</td><td>631,438,157</td></tr>
<tr><td>增減百分比</td><td>35.61</td></tr>
<tr><td>備註 / 營收變化原因說明</td><td>因先進製程產品需求增加所致。</td></tr>
</table></body></html>""".encode()


class FakeTransport:
    def __init__(self, body=HTML):
        self.body = body
        self.preloads = []
        self.posts = []

    def preload(self, endpoint):
        self.preloads.append(endpoint)

    def post(self, endpoint, payload):
        self.posts.append((endpoint, payload))
        return self.body


def _collect(tmp_path, transport):
    return MopsMonthlyRevenueCollector(
        transport=transport,
        filing_store=FilingStore(tmp_path / "store"),
    ).collect_month(
        security_code="2330",
        company_name="台灣積體電路製造股份有限公司",
        company_short_name="台積電",
        issuer_id="22099131",
        market="TWSE",
        month=RevenueMonth(115, 6),
        retrieved_at="2026-07-30T10:00:00+08:00",
        as_of="2026-07-30T10:00:00+08:00",
    )


def test_trailing_sixty_months_are_contiguous() -> None:
    months = trailing_months(RevenueMonth(115, 6))
    assert len(months) == 60
    assert months[0] == RevenueMonth(110, 7)
    assert months[-1] == RevenueMonth(115, 6)


def test_collects_and_parses_official_consolidated_monthly_revenue(tmp_path) -> None:
    artifact = _collect(tmp_path, FakeTransport())
    assert artifact.month == "115-06"
    assert artifact.report_scope == "consolidated_ifrs"
    assert artifact.unit == "TWD_thousand"
    assert artifact.revenue_thousand_twd == Decimal("442679969")
    assert artifact.prior_year_revenue_thousand_twd == Decimal("263708978")
    assert artifact.yoy_percent == Decimal("67.87")
    assert artifact.cumulative_yoy_percent == Decimal("35.61")
    assert artifact.explanation == "因先進製程產品需求增加所致。"


def test_cache_hit_does_not_use_network(tmp_path) -> None:
    store = FilingStore(tmp_path / "store")
    first = FakeTransport()
    kwargs = dict(
        security_code="2330",
        company_name="台灣積體電路製造股份有限公司",
        company_short_name="台積電",
        issuer_id="22099131",
        market="TWSE",
        month=RevenueMonth(115, 6),
        retrieved_at="2026-07-30T10:00:00+08:00",
        as_of="2026-07-30T10:00:00+08:00",
    )
    MopsMonthlyRevenueCollector(first, store).collect_month(**kwargs)

    class NoNetwork:
        def preload(self, endpoint):
            raise AssertionError("network must not be used")

        def post(self, endpoint, payload):
            raise AssertionError("network must not be used")

    hit = MopsMonthlyRevenueCollector(NoNetwork(), store).collect_month(**kwargs)
    assert hit.revenue_thousand_twd == Decimal("442679969")


@pytest.mark.parametrize(
    "body, message",
    [
        (HTML.replace("台積電".encode(), "其他公司".encode()), "company mismatch"),
        (HTML.replace("115年06月".encode(), "115年05月".encode()), "period mismatch"),
    ],
)
def test_rejects_wrong_identity_or_period(tmp_path, body, message) -> None:
    with pytest.raises(MonthlyRevenueError, match=message):
        _collect(tmp_path, FakeTransport(body))
