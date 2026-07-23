#!/usr/bin/env python3
"""Verify E0 immutable planning bindings; no product behavior."""
from __future__ import annotations
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "docs/specs/company-quality-product-spec.md": "36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161",
    "docs/planning/company-quality-decision-map.md": "cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54",
    "docs/planning/company-quality-multi-agent-delivery-plan.md": "bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0",
}
EXPECTED_R9 = "f3f2167aff87623caf74c44135b852384035e8cf276ddd46221506c9995859fb"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

for rel, expected in EXPECTED.items():
    actual = sha(ROOT / rel)
    if actual != expected:
        raise SystemExit(f"binding mismatch: {rel}: {actual} != {expected}")

work_orders = sorted((ROOT / "docs/work-orders/r9").glob("*.md"))
if len(work_orders) != 28:
    raise SystemExit(f"expected 28 R9 work orders, got {len(work_orders)}")
manifest = "\n".join(f"{p.name} {sha(p)}" for p in work_orders)
actual_set = hashlib.sha256(manifest.encode()).hexdigest()
if actual_set != EXPECTED_R9:
    raise SystemExit(f"R9 set mismatch: {actual_set} != {EXPECTED_R9}")

for p in work_orders:
    text = p.read_text(encoding="utf-8")
    if "not authorized" not in text.lower():
        raise SystemExit(f"authorization boundary missing: {p.name}")

print(f"E0_VERIFY PASS | authorities=3 | work_orders=28 | r9={actual_set}")
