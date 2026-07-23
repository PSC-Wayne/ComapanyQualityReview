from pathlib import Path

from tools.admission_scan import _is_exact_sha, _owned, _secret_findings


def test_owned_path_matching_supports_relative_and_authoritative_absolute_paths(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    assert _owned("src/company_quality/runtime/a.py", ["src/company_quality/runtime/"], root)
    assert _owned("pyproject.toml", [str(root / "pyproject.toml")], root)
    assert not _owned("src/company_quality/runtime_evil/a.py", ["src/company_quality/runtime/"], root)
    assert not _owned("pyproject.toml", [str(root.parent / "pyproject.toml")], root)


def test_exact_candidate_sha_rejects_refs_and_abbreviations() -> None:
    assert _is_exact_sha("a" * 40)
    assert not _is_exact_sha("a" * 12)
    assert not _is_exact_sha("HEAD")
    assert not _is_exact_sha("refs/heads/main")


def test_secret_scan_detects_tokens_private_keys_and_secret_filenames() -> None:
    fake_token = "gh" + "p_" + ("A" * 36)
    private_header = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
    patch = (
        "diff --git a/owned.py b/owned.py\n"
        "+++ b/owned.py\n"
        "+credential = '" + fake_token + "'\n"
        "+key = '" + private_header + "'\n"
    )

    findings = _secret_findings(
        patch.encode(),
        ["owned.py", "config/.env.production"],
        {"owned.py": patch.encode()},
    )

    assert any("GitHub token" in finding for finding in findings)
    assert any("private key" in finding for finding in findings)
    assert any("secret filename" in finding for finding in findings)


def test_clean_diff_has_no_secret_findings() -> None:
    patch = b"diff --git a/owned.py b/owned.py\n+++ b/owned.py\n+value = 42\n"
    assert _secret_findings(patch, ["owned.py"], {"owned.py": b"value = 42\n"}) == []
