# Company Quality Review

Taiwan listed/OTC company-quality research system.

## Current state

- Frozen product specification and R9 work orders are approved for controlled delivery.
- E0 repository/control-plane bootstrap is authorized.
- Product implementation (T01–T28) is **not authorized** until Wayne explicitly issues the next GO.
- The system is analysis-only: no trading, orders, broker mutation, deployment, scheduling or production writes.

## Authoritative planning artifacts

- `docs/specs/company-quality-product-spec.md`
- `docs/planning/company-quality-decision-map.md`
- `docs/planning/company-quality-multi-agent-delivery-plan.md`
- `docs/work-orders/r9/`

## E0 verification

```bash
python tools/e0_verify.py
```

All changes must use a Pull Request. Direct pushes to protected `main` are forbidden after bootstrap.
