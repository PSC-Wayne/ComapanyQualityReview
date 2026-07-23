#!/usr/bin/env python3
"""Fail-closed candidate admission for assignment-owned Git changes."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout


def _owned(path: str, owned_paths: list[str]) -> bool:
    normalized = PurePosixPath(path).as_posix()
    for owned in owned_paths:
        owned_normalized = PurePosixPath(owned).as_posix()
        if owned.endswith("/") and normalized.startswith(owned_normalized.rstrip("/") + "/"):
            return True
        if normalized == owned_normalized:
            return True
    return False


def _secret_findings(diff: str, changed_paths: list[str]) -> list[str]:
    findings: list[str] = []
    forbidden_names = re.compile(r"(^|/)(?:\.env(?:\..*)?|id_(?:rsa|ed25519))$|\.(?:pem|p12|pfx|key)$", re.I)
    for path in changed_paths:
        if forbidden_names.search(path):
            findings.append(f"secret-like filename: {path}")

    begin_private_key = "-----" + "BEGIN " + "PRIVATE KEY-----"
    patterns = [
        ("private-key material", re.compile(re.escape(begin_private_key))),
        ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
        ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
        (
            "assigned secret",
            re.compile(r"(?i)(?:password|passwd|api[_-]?key|secret|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
        ),
    ]
    added_lines = [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    for number, line in enumerate(added_lines, start=1):
        for label, pattern in patterns:
            if pattern.search(line):
                findings.append(f"{label} in added line {number}")
    return sorted(set(findings))


def _load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"parent_sha", "worktree", "owned_paths"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise ValueError("manifest is missing parent_sha, worktree, or owned_paths")
    if not isinstance(value["owned_paths"], list) or not all(
        isinstance(item, str) and item for item in value["owned_paths"]
    ):
        raise ValueError("manifest owned_paths must be a non-empty string list")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--forbid-secrets", action="store_true")
    parser.add_argument("--forbid-unowned", action="store_true")
    args = parser.parse_args(argv)

    if not args.forbid_secrets or not args.forbid_unowned:
        print("ADMISSION_FAIL both --forbid-secrets and --forbid-unowned are required", file=sys.stderr)
        return 2

    try:
        manifest = _load_manifest(args.manifest)
        root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip()).resolve()
        expected_root = Path(manifest["worktree"]).resolve()
        if root != expected_root:
            raise ValueError(f"worktree mismatch: expected {expected_root}, got {root}")
        parent = str(manifest["parent_sha"])
        candidate = _git(root, "rev-parse", "--verify", f"{args.candidate}^{{commit}}").strip()
        resolved_parent = _git(root, "rev-parse", "--verify", f"{parent}^{{commit}}").strip()
        _git(root, "merge-base", "--is-ancestor", resolved_parent, candidate)
        changed_paths = sorted(
            path for path in _git(root, "diff", "--name-only", resolved_parent, candidate).splitlines() if path
        )
        if not changed_paths:
            raise ValueError("candidate diff is empty")
        unowned = [path for path in changed_paths if not _owned(path, manifest["owned_paths"])]
        if unowned:
            raise ValueError("unowned paths: " + ", ".join(unowned))
        patch = _git(root, "diff", "--no-ext-diff", "--unified=0", resolved_parent, candidate)
        secret_findings = _secret_findings(patch, changed_paths)
        if secret_findings:
            raise ValueError("secret admission findings: " + "; ".join(secret_findings))
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"ADMISSION_FAIL {exc}", file=sys.stderr)
        return 1

    print(
        f"ADMISSION_PASS parent={resolved_parent} candidate={candidate} paths={len(changed_paths)} secrets=clear owned=clear"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
