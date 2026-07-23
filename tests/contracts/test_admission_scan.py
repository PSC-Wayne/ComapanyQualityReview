import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.admission_scan import _is_exact_sha, _owned, _parse_time, _secret_findings, main

AUTHORITY = {
    "spec_sha": "docs/specs/company-quality-product-spec.md",
    "decision_map_sha": "docs/planning/company-quality-decision-map.md",
    "delivery_plan_sha": "docs/planning/company-quality-multi-agent-delivery-plan.md",
    "work_order_sha": "docs/work-orders/r9/01-golden-path.md",
}


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


@pytest.mark.parametrize("value", ["20260724T010000+08:00", "2026-W30-5T01:00:00+08:00", "2026-07-24"])
def test_assignment_times_require_strict_rfc3339(value: str) -> None:
    with pytest.raises(ValueError):
        _parse_time(value, "lease_expires_at")


def test_secret_scan_detects_tokens_private_keys_binary_bytes_and_secret_filenames() -> None:
    fake_token = "gh" + "p_" + ("A" * 36)
    headers = [
        "-----BEGIN " + kind + " PRIVATE KEY-----"
        for kind in ("RSA", "EC", "OPENSSH")
    ]
    patch = (
        "diff --git a/owned.py b/owned.py\n+++ b/owned.py\n"
        "+credential = '" + fake_token + "'\n"
    ).encode()
    blob = b"\x00binary\x00" + "\n".join(headers).encode()

    findings = _secret_findings(
        patch,
        ["owned.py", "config/.env.production"],
        {"owned.py": patch, "asset.bin": blob},
    )

    assert any("GitHub token" in finding for finding in findings)
    assert any("private key" in finding for finding in findings)
    assert any("secret filename" in finding for finding in findings)


def test_clean_diff_has_no_secret_findings() -> None:
    patch = b"diff --git a/owned.py b/owned.py\n+++ b/owned.py\n+value = 42\n"
    assert _secret_findings(patch, ["owned.py"], {"owned.py": b"value = 42\n"}) == []


def _run(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-b", "test")
    _run(repo, "config", "user.email", "test@example.invalid")
    _run(repo, "config", "user.name", "T01 Test")
    for relative in AUTHORITY.values():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative + "\n", encoding="utf-8")
    (repo / "owned.txt").write_text("owned\n", encoding="utf-8")
    (repo / "forbidden.txt").write_text("forbidden\n", encoding="utf-8")
    _run(repo, "add", ".")
    _run(repo, "commit", "-m", "base")
    return repo, _run(repo, "rev-parse", "HEAD")


def _manifest(repo: Path, parent: str, owned_paths: list[str]) -> Path:
    now = datetime.now(timezone.utc)
    data: dict[str, object] = {
        "assignment_id": "95adf90d-6f4b-4b32-a3e7-7fcf2e7ca3f0",
        "active_binding_generation": 1,
        "eligibility_generation": 3,
        "ticket_id": "T01",
        "ticket_generation": "R9",
        "authorization": "GO-T01",
        "issued_at": (now - timedelta(minutes=1)).isoformat(),
        "lease_expires_at": (now + timedelta(hours=1)).isoformat(),
        "review_deadline_at": (now + timedelta(hours=1)).isoformat(),
        "repository": "PSC-Wayne/ComapanyQualityReview",
        "parent_sha": parent,
        "branch": "test",
        "worktree": str(repo),
        "owned_paths": owned_paths,
        "ticket_set_digest": "a" * 64,
        "network_allowed": False,
        "product_scope": "T01_ONLY",
        "stop_after_ticket": True,
    }
    for field, relative in AUTHORITY.items():
        data[field] = hashlib.sha256((repo / relative).read_bytes()).hexdigest()
    path = repo / ".git" / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_actual_scan_rejects_unowned_deletion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, parent = _repo(tmp_path)
    (repo / "forbidden.txt").unlink()
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "delete forbidden")
    candidate = _run(repo, "rev-parse", "HEAD")
    manifest = _manifest(repo, parent, ["owned.txt"])
    monkeypatch.chdir(repo)
    assert main(["--candidate", candidate, "--forbid-unowned", "--manifest", str(manifest)]) == 1


def test_actual_scan_rejects_non_regular_git_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, parent = _repo(tmp_path)
    _run(repo, "update-index", "--add", "--cacheinfo", f"160000,{parent},owned-link")
    _run(repo, "commit", "-m", "add gitlink")
    candidate = _run(repo, "rev-parse", "HEAD")
    manifest = _manifest(repo, parent, ["owned-link"])
    monkeypatch.chdir(repo)
    assert main(["--candidate", candidate, "--forbid-unowned", "--manifest", str(manifest)]) == 1


def test_authority_hash_is_checked_against_candidate_blob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, parent = _repo(tmp_path)
    (repo / "owned.txt").write_text("changed\n", encoding="utf-8")
    _run(repo, "add", "owned.txt")
    _run(repo, "commit", "-m", "change owned")
    candidate = _run(repo, "rev-parse", "HEAD")
    manifest = _manifest(repo, parent, ["owned.txt"])
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["spec_sha"] = hashlib.sha256(b"not candidate bytes").hexdigest()
    manifest.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.chdir(repo)
    assert main(["--candidate", candidate, "--forbid-unowned", "--manifest", str(manifest)]) == 1
