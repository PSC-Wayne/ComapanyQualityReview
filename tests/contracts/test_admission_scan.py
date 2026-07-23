from tools.admission_scan import _owned, _secret_findings


def test_owned_path_matching_is_exact_or_directory_bounded() -> None:
    owned = ["pyproject.toml", "src/company_quality/runtime/"]

    assert _owned("pyproject.toml", owned)
    assert _owned("src/company_quality/runtime/contracts/result.json", owned)
    assert not _owned("pyproject.toml.bak", owned)
    assert not _owned("src/company_quality/runtime-escape/file.py", owned)


def test_secret_scan_detects_secret_material_and_secret_filenames() -> None:
    fake_token = "gh" + "p_" + ("A" * 36)
    patch = (
        "diff --git a/owned.py b/owned.py\n"
        "+++ b/owned.py\n"
        "+credential = '" + fake_token + "'\n"
    )

    findings = _secret_findings(patch, ["owned.py", "config/.env.production"])

    assert any("GitHub token" in finding for finding in findings)
    assert any("secret-like filename" in finding for finding in findings)


def test_secret_scan_does_not_flag_normal_source_vocabulary() -> None:
    patch = "+error_code = 'blocked_contract'\n+rating_disposition = 'NO_RATING_NOT_APPLICABLE'\n"

    assert _secret_findings(patch, ["src/company_quality/runtime/__init__.py"]) == []
