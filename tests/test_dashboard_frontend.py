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


def test_dashboard_rejects_pre_v4_or_cross_generation_checklist() -> None:
    assert "report.schema_version==='SingleCompanyResearchReport.v4'" in INDEX_HTML
    assert "report.checklist_assessment.generation_id===currentGeneration" in INDEX_HTML
    assert "此報告沒有權威Checklist assessment" in INDEX_HTML
