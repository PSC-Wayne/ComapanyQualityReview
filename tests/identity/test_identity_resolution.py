from company_quality.identity import OfficialIdentitySource, resolve_identity


TWSE = OfficialIdentitySource(
    market="TWSE",
    url="https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    available_at="2026-07-24T00:00:00+08:00",
    rows=(
        {
            "security_code": "2330",
            "company_name": "台灣積體電路製造股份有限公司",
            "short_name": "台積電",
            "issuer_id": "22099131",
            "listing_date": "19940905",
        },
    ),
)

TPEX = OfficialIdentitySource(
    market="TPEx",
    url="https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
    available_at="2026-07-24T00:00:00+08:00",
    rows=(
        {
            "security_code": "9999",
            "company_name": "測試科技股份有限公司",
            "short_name": "台積電",
            "issuer_id": "12345678",
            "listing_date": "20200102",
        },
    ),
)


def test_resolves_code_or_company_name_in_requested_market() -> None:
    by_code = resolve_identity(
        "2330", "TWSE", "2026-07-24T12:00:00+08:00", (TWSE, TPEX)
    )
    by_name = resolve_identity(
        "台積電", "TWSE", "2026-07-24T12:00:00+08:00", (TWSE, TPEX)
    )

    assert by_code.status == by_name.status == "resolved"
    assert by_code.identity == by_name.identity
    assert by_code.identity is not None
    assert by_code.identity.security_id == "TWSE:2330"
    assert by_code.identity.issuer_id == "22099131"
    assert by_code.identity.company_name == "台灣積體電路製造股份有限公司"
    assert by_code.identity.valid_from == "1994-09-05T00:00:00+08:00"


def test_market_mismatch_and_unknown_are_distinct() -> None:
    mismatch = resolve_identity(
        "2330", "TPEx", "2026-07-24T12:00:00+08:00", (TWSE, TPEX)
    )
    unknown = resolve_identity(
        "0000", "TWSE", "2026-07-24T12:00:00+08:00", (TWSE, TPEX)
    )

    assert mismatch.status == "not_found_in_requested_market"
    assert unknown.status == "not_found"
    assert mismatch.identity is None and unknown.identity is None


def test_name_ambiguity_is_not_guessed_without_market() -> None:
    result = resolve_identity(
        "台積電", None, "2026-07-24T12:00:00+08:00", (TWSE, TPEX)
    )

    assert result.status == "ambiguous_identity"
    assert result.identity is None


def test_invalid_or_pre_snapshot_decision_time_fails_explicitly() -> None:
    invalid = resolve_identity("2330", "TWSE", "2026-07-24", (TWSE, TPEX))
    historical = resolve_identity(
        "2330", "TWSE", "2026-07-23T23:59:59+08:00", (TWSE, TPEX)
    )

    assert invalid.status == "invalid_decision_time"
    assert historical.status == "historical_identity_unresolved"
    assert invalid.identity is None and historical.identity is None
