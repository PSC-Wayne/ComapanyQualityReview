import json

from company_quality.company_analysis.checklist_analysis import _placeholder_checks
from company_quality.sources.governance_insiders import (
    GovernanceInsiderProducer,
    MaterialEventHistory,
    apply_governance_checks,
)


AS_OF = "2026-08-03T12:00:00+08:00"


class FakeTransport:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def fetch(self, url: str) -> bytes:
        self.calls.append(url)
        return json.dumps(self.payloads.get(url, []), ensure_ascii=False).encode()


def _producer(market, payloads, history=None):
    producer = GovernanceInsiderProducer(
        transport=FakeTransport(payloads),
        material_event_history=history,
    )
    code = "2330" if market == "TWSE" else "6488"
    name = "台積電" if market == "TWSE" else "環球晶"
    evidence = producer.produce(
        issuer_id="22099131" if market == "TWSE" else "28113286",
        security_code=code,
        reported_company_name=name,
        market=market,
        as_of=AS_OF,
    )
    assert producer.last_collection is not None
    return producer.last_collection, evidence


def test_twse_and_tpex_holdings_use_official_windows_and_preserve_snapshot_row_identity():
    twse_url = "https://openapi.twse.com.tw/v1/opendata/t187ap11_L"
    tpex_url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O"
    twse, twse_evidence = _producer("TWSE", {twse_url: [{
        "出表日期": "1150720", "資料年月": "11506", "公司代號": "2330",
        "公司名稱": "台積電", "職稱": "董事長本人", "姓名": "魏哲家",
        "選任時持股 ": "7000", "目前持股": "7000", "設質股數": "0",
        "設質股數佔持股比例": "0.00%", "內部人關係人目前持股合計": "0",
        "內部人關係人設質股數": "0", "內部人關係人設質比例": "0.00%",
    }]})
    tpex, tpex_evidence = _producer("TPEx", {tpex_url: [{
        "出表日期": "1150720", "資料年月": "11506", "公司代號": "6488",
        "公司名稱": "環球晶", "職稱": "董事長本人", "姓名": "徐秀蘭",
        "選任時持股": "100", "目前持股": "100", "設質股數": "0",
        "設質股數佔持股比例": "0.00%", "內部人關係人目前持股合計": "0",
        "內部人關係人設質股數": "0", "內部人關係人設質比例": "0.00%",
    }]})

    assert twse.events[0].dataset_id == "t187ap11_L"
    assert tpex.events[0].dataset_id == "mopsfin_t187ap11_O"
    assert twse.events[0].observed_period == "11506"
    assert "row_sha256:" in twse.events[0].source_locator
    assert twse.events[0].checklist_ids == ("R41",)
    assert twse_evidence[0].evidence_role == "substantive"
    assert tpex_evidence[0].evidence_role == "substantive"


def test_transfer_declaration_is_intent_and_never_executed_sale_proof():
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap12_L"
    collection, evidence = _producer("TWSE", {url: [{
        "出表日期": "1150731", "公司代號": "2330", "公司名稱": "台積電",
        "申報人身分": "董事本人", "姓名": "曾繁城",
        "預定轉讓方式及股數-轉讓方式": "贈與",
        "預定轉讓總股數-自有持股": "5000000", "有效轉讓期間": "1150731~1150802",
    }]})

    event = collection.events[0]
    assert event.event_type == "transfer_intent"
    assert event.evidence_role == "discovery"
    assert event.checklist_ids == ()
    assert "不證明已完成轉讓" in event.counterevidence[0]
    assert evidence[0].evidence_role == "discovery"


def test_r41_holding_decline_is_triggered_but_single_current_snapshot_stays_unresolved():
    rows = [
        {"出表日期": "1150620", "資料年月": "11505", "公司代號": "2330", "公司名稱": "台積電", "職稱": "董事本人", "姓名": "甲", "目前持股": "100", "設質股數": "0", "設質股數佔持股比例": "0.00%"},
        {"出表日期": "1150720", "資料年月": "11506", "公司代號": "2330", "公司名稱": "台積電", "職稱": "董事本人", "姓名": "甲", "目前持股": "80", "設質股數": "0", "設質股數佔持股比例": "0.00%"},
    ]
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap11_L"
    collection, _ = _producer("TWSE", {url: rows})
    checks = {item.check_id: item for item in apply_governance_checks(_placeholder_checks("missing"), collection)}
    assert checks["R41"].status == "evaluated"
    assert checks["R41"].applicability == "triggered"
    assert checks["R41"].financial_period == "11506"
    assert checks["R41"].counterevidence

    current, _ = _producer("TWSE", {url: rows[-1:]})
    row = {item.check_id: item for item in apply_governance_checks(_placeholder_checks("missing"), current)}["R41"]
    assert row.status == "unresolved"
    assert "單一月份" in row.unresolved_reasons[0]


def test_r41_can_be_not_triggered_only_with_two_complete_snapshots_and_zero_pledges():
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap11_L"
    rows = [
        {"出表日期": "1150620", "資料年月": "11505", "公司代號": "2330", "公司名稱": "台積電", "職稱": "董事本人", "姓名": "甲", "目前持股": "100", "設質股數": "0", "設質股數佔持股比例": "0.00%"},
        {"出表日期": "1150720", "資料年月": "11506", "公司代號": "2330", "公司名稱": "台積電", "職稱": "董事本人", "姓名": "甲", "目前持股": "110", "設質股數": "0", "設質股數佔持股比例": "0.00%"},
    ]
    collection, _ = _producer("TWSE", {url: rows})
    row = {item.check_id: item for item in apply_governance_checks(_placeholder_checks("missing"), collection)}["R41"]
    assert row.status == "evaluated"
    assert row.applicability == "not_triggered"


def _history(*subjects, complete=True):
    records = tuple({
        "market": "TWSE", "security_code": "2330", "company_name": "台積電",
        "announced_at": f"202{index + 2}-05-01T18:30:00+08:00",
        "effective_date": f"202{index + 2}-05-01", "subject": subject,
        "detail": f"事實發生日：202{index + 2}-05-01；{subject}",
        "source_locator": f"sii:2330:serial:{index + 1}",
    } for index, subject in enumerate(subjects))
    return MaterialEventHistory(
        window_start="2021-08-03", window_end="2026-08-03",
        complete=complete, records=records,
        source_url="https://mops.twse.com.tw/mops/api/t05st02",
    )


def test_r42_requires_bounded_mops_history_and_effective_dates_for_frequent_changes():
    collection, _ = _producer("TWSE", {}, _history("公告財務主管異動", "公告稽核主管異動"))
    rows = {item.check_id: item for item in apply_governance_checks(_placeholder_checks("missing"), collection)}
    row = rows["R42"]
    assert row.status == "evaluated"
    assert row.applicability == "triggered"
    assert row.first_detectable_at == "2023-05-01T18:30:00+08:00"
    assert row.financial_period == "2023-05-01"
    assert len(row.evidence_ids) == 2


def test_r42_not_triggered_requires_complete_history_and_incomplete_absence_is_unresolved():
    complete, _ = _producer("TWSE", {}, _history())
    row = {item.check_id: item for item in apply_governance_checks(_placeholder_checks("missing"), complete)}["R42"]
    assert row.status == "evaluated"
    assert row.applicability == "not_triggered"

    incomplete, _ = _producer("TWSE", {}, _history(complete=False))
    row = {item.check_id: item for item in apply_governance_checks(_placeholder_checks("missing"), incomplete)}["R42"]
    assert row.status == "unresolved"
    assert "不能證明沒有異動" in row.unresolved_reasons[0]


def test_control_change_and_generic_penalty_remain_context_without_invented_check_ids():
    control = "https://openapi.twse.com.tw/v1/opendata/t187ap24_L"
    penalty = "https://openapi.twse.com.tw/v1/opendata/t187ap22_L"
    collection, _ = _producer("TWSE", {
        control: [{"出表日期": "1150802", "公司代號": "2330", "公司名稱": "台積電", "經營權異動日期": "1150629", "經營權異動說明": "董事改選造成經營權異動"}],
        penalty: [{"出表日期": "1150802", "發函日期": "1150518", "股票代號": "2330", "公司名稱": "台積電", "違規事由": "未依期限公告", "違反法規": "證券交易法", "裁處情形": "罰鍰"}],
    })
    assert {event.event_type for event in collection.events} == {"control_change", "regulatory_penalty"}
    assert all(event.checklist_ids == () for event in collection.events)

