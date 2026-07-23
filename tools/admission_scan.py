#!/usr/bin/env python3
"""Fail-closed admission scan for one exact T01 Git candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,255}")),
    ("AWS access key", re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}")),
    ("assigned secret", re.compile(rb"(?i)(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"\r\n]{8,}['\"]")),
)
_SECRET_NAMES = re.compile(
    r"(?i)(?:^|/)(?:\.env(?:\..+)?|id_(?:rsa|dsa|ecdsa|ed25519)|[^/]*\.(?:pem|key|p12|pfx|jks|keystore))$"
)
_REQUIRED_MANIFEST = {
    "assignment_id",
    "active_binding_generation",
    "eligibility_generation",
    "ticket_id",
    "ticket_generation",
    "authorization",
    "issued_at",
    "lease_expires_at",
    "review_deadline_at",
    "repository",
    "parent_sha",
    "branch",
    "worktree",
    "owned_paths",
    "spec_sha",
    "decision_map_sha",
    "delivery_plan_sha",
    "work_order_sha",
    "ticket_set_digest",
    "network_allowed",
    "product_scope",
    "stop_after_ticket",
}
_AUTHORITY_FILES = {
    "spec_sha": "docs/specs/company-quality-product-spec.md",
    "decision_map_sha": "docs/planning/company-quality-decision-map.md",
    "delivery_plan_sha": "docs/planning/company-quality-multi-agent-delivery-plan.md",
    "work_order_sha": "docs/work-orders/r9/01-golden-path.md",
}


def _git(*args: str, binary: bool = False) -> str | bytes:
    return subprocess.check_output(
        ["git", *args], stderr=subprocess.STDOUT, text=not binary
    )


def _is_exact_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA40.fullmatch(value) is not None


def _manifest_owned_entry(entry: str, root: Path) -> tuple[str, bool] | None:
    directory = entry.endswith("/")
    raw = Path(entry.rstrip("/"))
    if raw.is_absolute():
        try:
            raw = raw.relative_to(root)
        except ValueError:
            return None
    normalized = PurePosixPath(raw.as_posix()).as_posix()
    if normalized in ("", ".") or normalized == ".." or normalized.startswith("../"):
        return None
    return normalized, directory


def _owned(path: str, owned_paths: list[str], root: Path) -> bool:
    candidate = PurePosixPath(path).as_posix()
    for entry in owned_paths:
        normalized = _manifest_owned_entry(entry, root)
        if normalized is None:
            continue
        authority, directory = normalized
        if candidate == authority or (directory and candidate.startswith(authority + "/")):
            return True
    return False


def _secret_findings(
    patch: bytes, changed_paths: list[str], blobs: dict[str, bytes]
) -> list[str]:
    findings: set[str] = set()
    for path in changed_paths:
        if _SECRET_NAMES.search(path):
            findings.add(f"secret filename: {path}")
    added = b"\n".join(
        line[1:]
        for line in patch.splitlines()
        if line.startswith(b"+") and not line.startswith(b"+++")
    )
    surfaces = [("added diff", added), *[(f"blob {path}", data) for path, data in blobs.items()]]
    for label, surface in surfaces:
        for name, pattern in _SECRET_PATTERNS:
            if pattern.search(surface):
                findings.add(f"{name} in {label}")
    return sorted(findings)


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        raise ValueError(f"{field} must be RFC3339")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _has_symlink_component(path: Path, stop: Path) -> bool:
    current = path
    while current != stop:
        if current.is_symlink():
            return True
        if stop not in current.parents:
            return True
        current = current.parent
    return stop.is_symlink()


def _validate_manifest(manifest: dict[str, Any], root: Path, candidate: str) -> str:
    missing = sorted(_REQUIRED_MANIFEST - manifest.keys())
    if missing:
        raise ValueError(f"manifest missing fields: {missing}")
    if manifest["ticket_id"] != "T01" or manifest["authorization"] != "GO-T01":
        raise ValueError("manifest ticket/authorization mismatch")
    if manifest["network_allowed"] is not False or manifest["product_scope"] != "T01_ONLY":
        raise ValueError("manifest scope is not T01 fail-closed")
    if manifest["stop_after_ticket"] is not True:
        raise ValueError("manifest stop_after_ticket must be true")
    if not _is_exact_sha(manifest["parent_sha"]):
        raise ValueError("manifest parent_sha must be exact")
    for field in ("spec_sha", "decision_map_sha", "delivery_plan_sha", "work_order_sha", "ticket_set_digest"):
        if not isinstance(manifest[field], str) or _SHA64.fullmatch(manifest[field]) is None:
            raise ValueError(f"manifest {field} must be SHA-256")
    if not isinstance(manifest["owned_paths"], list) or not manifest["owned_paths"]:
        raise ValueError("manifest owned_paths must be non-empty")
    if any(_manifest_owned_entry(str(entry), root) is None for entry in manifest["owned_paths"]):
        raise ValueError("manifest contains owned path outside worktree")
    manifest_root = Path(manifest["worktree"])
    if manifest_root.resolve() != root or _has_symlink_component(manifest_root, manifest_root.anchor and Path(manifest_root.anchor) or root):
        raise ValueError("manifest worktree mismatch or symlink")
    branch = str(_git("branch", "--show-current")).strip() or "DETACHED"
    if manifest["branch"] != branch:
        raise ValueError(f"manifest branch mismatch: expected {manifest['branch']} actual {branch}")
    now = datetime.now().astimezone()
    if _parse_time(manifest["issued_at"], "issued_at") > now:
        raise ValueError("manifest issued_at is in the future")
    if now >= _parse_time(manifest["lease_expires_at"], "lease_expires_at"):
        raise ValueError("manifest lease expired")
    if now >= _parse_time(manifest["review_deadline_at"], "review_deadline_at"):
        raise ValueError("manifest review deadline expired")
    resolved = str(_git("rev-parse", "--verify", f"{candidate}^{{commit}}")).strip()
    head = str(_git("rev-parse", "HEAD")).strip()
    if resolved != candidate or head != candidate:
        raise ValueError("candidate must be exact current HEAD")
    if str(_git("status", "--porcelain=v1")).strip():
        raise ValueError("candidate worktree must be clean")
    return str(manifest["parent_sha"])


def _verify_authorities(manifest: dict[str, Any], candidate: str) -> None:
    for field, relative in _AUTHORITY_FILES.items():
        blob = _git("show", f"{candidate}:{relative}", binary=True)
        assert isinstance(blob, bytes)
        digest = hashlib.sha256(blob).hexdigest()
        if digest != manifest[field]:
            raise ValueError(f"authority hash mismatch: {field}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--forbid-secrets", action="store_true")
    parser.add_argument("--forbid-unowned", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not _is_exact_sha(args.candidate):
            raise ValueError("--candidate must be a full 40-character lowercase Git SHA")
        root = Path.cwd().resolve()
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest root must be an object")
        parent = _validate_manifest(manifest, root, args.candidate)
        _verify_authorities(manifest, args.candidate)
        raw_paths = _git("diff", "--name-only", "-z", "--diff-filter=ACMRTD", parent, args.candidate, binary=True)
        assert isinstance(raw_paths, bytes)
        paths = [item.decode("utf-8") for item in raw_paths.split(b"\0") if item]
        if not paths:
            raise ValueError("candidate diff is empty")
        if args.forbid_unowned:
            unowned = [path for path in paths if not _owned(path, manifest["owned_paths"], root)]
            if unowned:
                raise ValueError(f"unowned paths: {unowned}")
        blobs: dict[str, bytes] = {}
        for path in paths:
            tree_entry = str(_git("ls-tree", args.candidate, "--", path)).strip()
            if not tree_entry:
                continue
            mode = tree_entry.split(maxsplit=1)[0]
            if mode not in {"100644", "100755"}:
                raise ValueError(f"disallowed Git mode {mode}: {path}")
            live = root / path
            if _has_symlink_component(live, root):
                raise ValueError(f"symlink path component: {path}")
            blob = _git("show", f"{args.candidate}:{path}", binary=True)
            assert isinstance(blob, bytes)
            blobs[path] = blob
        if args.forbid_secrets:
            patch = _git("diff", "--binary", parent, args.candidate, binary=True)
            assert isinstance(patch, bytes)
            findings = _secret_findings(patch, paths, blobs)
            if findings:
                raise ValueError(f"secret admission findings: {findings}")
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ADMISSION_FAIL {exc}", file=sys.stderr)
        return 1
    print(
        f"ADMISSION_PASS parent={parent} candidate={args.candidate} "
        f"paths={len(paths)} secrets=clear owned=clear"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
