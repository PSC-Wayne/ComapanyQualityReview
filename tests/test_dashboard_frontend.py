from company_quality.dashboard_frontend import INDEX_HTML


def test_authoritative_checklist_is_a_first_class_dashboard_section() -> None:
    assert 'id="authority-checklist"' in INDEX_HTML
    assert 'id="checklist-assessment"' in INDEX_HTML
    assert "權威詳細檢查完成狀態" in INDEX_HTML
    assert "報告生成完成不等於詳細檢查完成" in INDEX_HTML
    assert "完成條件 ${completeCoverage}/${coverage.length}" in INDEX_HTML
    assert "逐題檢查 ${evaluated}/${checks.length}" in INDEX_HTML
    assert "需求到現金傳導" in INDEX_HTML
    assert "七項成長結論" in INDEX_HTML
    assert "十項風險結論" in INDEX_HTML
    assert "未完成項目與後續驗證" in INDEX_HTML
    assert "五年年度＋最近四季財務總覽" in INDEX_HTML
    assert "G／R／N／A／產業逐題結果" in INDEX_HTML
    assert "產業路由：" in INDEX_HTML
    assert "查核與KAM" in INDEX_HTML
    assert "最低附註" in INDEX_HTML
    assert "overviewTable(a.financial_overview)" in INDEX_HTML
    assert "cash_conversion_cycle_days:'現金轉換週期'" in INDEX_HTML
    assert "common_stock_capital:'普通股股本'" in INDEX_HTML


def test_dashboard_rejects_pre_v4_or_cross_generation_checklist() -> None:
    assert "report.schema_version==='SingleCompanyResearchReport.v4'" in INDEX_HTML
    assert "report.checklist_assessment.generation_id===currentGeneration" in INDEX_HTML
    assert "此報告沒有權威Checklist assessment" in INDEX_HTML
