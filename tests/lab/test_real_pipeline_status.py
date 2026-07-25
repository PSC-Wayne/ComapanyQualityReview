import pandas as pd

from company_quality.lab.real_pipeline_status import build_real_pipeline_status


def test_real_pipeline_status_reports_exact_upstream_blockers():
    materializer_report = {
        "security_count": 3,
        "ready_security_count": 3,
        "official_identity": {
            "t20_status": "BLOCKED_INCOMPLETE_LEGAL_IDENTITY",
            "security_membership_coverage": 1.0,
            "legal_identity_coverage": 2 / 3,
        },
    }
    identity = pd.DataFrame([
        {
            "security_code": "2330",
            "market": "sii",
            "identity_status": "CURRENT_OFFICIAL_IDENTITY",
            "legal_identity_resolved": True,
            "listed_on": "1994-09-05",
            "delisted_on": None,
        },
        {
            "security_code": "6806",
            "market": "sii",
            "identity_status": "OFFICIAL_DELISTED_LEGAL_IDENTITY",
            "legal_identity_resolved": True,
            "listed_on": None,
            "delisted_on": "115/06/23",
        },
        {
            "security_code": "1258",
            "market": "otc",
            "identity_status": "OFFICIAL_DELISTED_SECURITY_LIFECYCLE",
            "legal_identity_resolved": False,
            "listed_on": None,
            "delisted_on": "110-12-15",
        },
    ])

    report = build_real_pipeline_status(materializer_report, identity)

    inventory = report["real_data_inventory"]
    assert report["execution_status"] == "BLOCKED_INPUT_DATA"
    assert inventory["price_ready_coverage"] == 1
    assert inventory["legal_identity_gap_count"] == 1
    assert inventory["delisted_listing_date_gap_count"] == 2
    assert report["stage_results"]["T20"]["status"] == (
        "BLOCKED_INCOMPLETE_LEGAL_IDENTITY"
    )
    assert report["stage_results"]["T21"]["status"] == "BLOCKED_UPSTREAM_T20"
    assert report["stage_results"]["T22"]["candidate_observation_count"] == 0
