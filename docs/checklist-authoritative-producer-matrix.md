# Authoritative checklist producer matrix

This is the final traceability matrix for
`Financial_Statement_Growth_Risk_Checklist.md`.  A row is not considered
complete merely because a producer exists: evidence must be issuer-bound,
period-bound, point-in-time eligible (`available_at <= as_of`), cited, and
publication-ready. Missing or conflicting evidence remains `unresolved`.

## Shared evidence contract

| Concern | Runtime owner | Rule |
|---|---|---|
| Official identity | `identity` + `evidence_producers.py` | Match market, security code and issuer ID; name alone cannot bind evidence. |
| Point in time | `evidence_bundle.py` + `evidence_producers.py` | Preserve period, report/announcement date, `available_at`, retrieval time and `as_of`; reject post-as-of evidence. |
| Citation | `contracts.EvidenceCitation` | Official URL, source ID, period, exact HTML locator or PDF page/bbox, verbatim excerpt and admitted evidence ID are required. |
| Source authority | Per-claim producer registry | TWSE/TPEx OpenAPI is authoritative only for fields it publishes; original MOPS filing, annual report, IR filing or note remains required where the claim needs it. |
| Failure behavior | `ChecklistCheckResult` / `ChecklistAssessment` | Missing horizon, denominator, note, KAM, roll-forward, terms, identity or source conflict stays `unresolved`; absence from a current feed is never “no risk”. |
| Publication | `report_orchestrator.py` | Core report status and detailed-checklist status are independent. A succeeded job does not imply a complete checklist. |

## Checklist rule ownership

| Rules | Producer / evaluator | Source windows | Citation / freshness | Fail-closed behavior | Primary tests |
|---|---|---|---|---|---|
| G01–G07, G09–G13, G19, G22–G23 | `checklist_analysis.py`, `checklist_metrics.py`, `history_context.py` | MOPS five-year annual statements, 12 quarters, 36–60 months revenue; annual report/IR evidence when the claim requires business explanation | Statement handles plus admitted document citations; same issuer, comparable period and PIT | Quantitative signal alone cannot complete explanatory/documentary predicates; zero/negative denominator and missing comparable periods stay unresolved | `test_checklist_contracts.py`, `test_checklist_metrics.py`, `test_history_context.py` |
| G08, G14–G18, G20–G21 | `growth_check_producers.py` | PIT-materialized statements, equity changes, original promise/guidance, contract/backlog, geography and acquisition evidence | Evidence handle per required fact; original promise date and measurement horizon preserved | Any missing fact, lineage, horizon or non-positive denominator fails closed | `test_growth_check_producers.py` |
| G24–G25 | `forecast_capital.py`, `history_context.py` | Original dividend resolutions; formal forecast filing and same-basis actual; dated IR guidance history | Proposal/approval/payment and guidance/actual citations remain distinct | Proposal is not payment; guidance is not formal forecast; absent historical horizon stays unresolved | `test_forecast_capital.py`, `test_history_context.py` |
| R01–R09, R19–R20 | `working_capital_risk.py` | Statements plus receivable/inventory/contract-asset/payable notes, KAM, subsequent collection/sale | Period-aligned fact IDs and exact note/KAM citations | Ratio screens only trigger follow-up; missing aging, ECL, roll-forward or subsequent evidence cannot produce a safety conclusion | `test_working_capital_risk.py` |
| R10–R18, R38 | `solvency_commitment_risk.py` | Debt and maturity notes, cash restrictions, signed facilities, covenant/waiver documents, lease and unpaid commitments | Contract terms and waiver timestamps must be available by `as_of` | Oral renewal/assertion is not financing; post-as-of waiver cannot repair PIT state; incomplete debt classes/terms stay unresolved | `test_solvency_commitment_risk.py` |
| R21–R28 | `checklist_analysis.py`, `checklist_evidence.py` | Statements, tax/fair-value/provision/capitalization/non-controlling-interest notes and KAM | Main-statement facts plus exact PDF note/KAM locator | Main-table movement without required note/model/roll-forward remains unresolved | `test_checklist_contracts.py`, `test_checklist_evidence.py` |
| R29–R36 | `impairment_capital_risk.py` | Business-combination, impairment, PPE/ROU, equity-method, financial-asset, related-party, lending and guarantee documents | Valuation assumptions, counterparty identity, terms and original official document IDs | Missing CGU/model/sensitivity, counterparty identity, terms or original document fails closed | `test_impairment_capital_risk.py` |
| R37, R40 | `esg_supply_chain.py` | Original litigation/contingency and supplier/key-material note or event; TWSE/TPEx ESG OpenAPI only as bounded context | Dataset, field, report year, issuer identity and original report/note citation | Anti-competition loss does not prove absence of litigation; supplier audit does not prove concentration; one long-contract mention cannot complete cancellation/demand predicates | `test_esg_supply_chain.py` |
| R39, R41–R42 | `evidence_producers.py` governance/control/insider producers + `checklist_analysis.py` | Annual report, official ownership/pledge/control records and MOPS executive/auditor events | Official issuer-bound record with event date and `available_at` | Current-feed miss does not establish no concentration, no pledge or no turnover; missing history stays unresolved | `test_evidence_producers.py`, `test_checklist_contracts.py` |
| R43–R48 | `forecast_capital.py` + capital-structure conclusion in `impairment_capital_risk.py` | MOPS capital events, prospectus/CB terms, share awards, dividend resolutions, acquisition, buyback and follow-up financials | Event lifecycle, original filing, terms, effective date and follow-up evidence are separate | Proposed/authorized is not completed; issued, weighted-average, diluted and fully diluted shares are not interchangeable | `test_forecast_capital.py`, `test_impairment_capital_risk.py` |
| N01–N19 | `checklist_evidence.py` | Annual audit PDFs and minimum notes: revenue through subsequent events | Exact PDF page/bbox, verbatim excerpt, period and official URL | Keyword absence or unreadable/missing PDF remains unresolved | `test_checklist_evidence.py` |
| Audit/KAM controls A01–A04 | `checklist_evidence.py`, `report_orchestrator.py` KAM timeline | Annual audit and quarterly review reports, opinion, going concern, emphasis/other matter and KAM | Report type, report date, page/bbox and cross-year citation | Review is not audit; KAM is not fraud; missing year/report cannot be treated as a clean opinion | `test_checklist_evidence.py`, `test_report_orchestrator.py` |
| I-MFG-01–I-MFG-06 | `manufacturing.py` (`I-MFG-03` original-source boundary also enforced by `esg_supply_chain.py`) | Annual report, production/capacity/yield, inventory split, commitments, customer/application, product lifecycle and FX evidence | Official company-level business-model route plus cited facts | Broad code/name cannot route; partial commitment or missing terms remains unresolved | `test_manufacturing_evidence.py`, `test_esg_supply_chain.py` |
| I-MFG-07 | `industry.peer_outlook` | Same-period official peer financials | Issuer-bound peer set and same-period evidence handles | Missing/comparability-conflicted peers stay unresolved; no synthetic peer data | `test_peer_outlook.py`, `test_checklist_contracts.py` |
| I-SW-01–I-SW-05 | `software_ai.py` | Company-level recurring revenue, renewal/churn, contract liabilities, capitalization, service cost/margin and share compensation | Official identity plus cited software/subscription business evidence | Broad industry code or company name alone cannot route; missing cohort/term/horizon stays unresolved | `test_software_ai.py` |
| I-BIO-01–I-BIO-05 | `special_industries.py` | Regulatory/product pipeline, trial/milestone, licensing, R&D/cash runway and concentration evidence | Official biotech business evidence, PIT milestone and source period | Candidate route or partial pipeline text is insufficient | `test_special_industries.py`, `test_industry_route.py` |
| I-ENERGY-01–I-ENERGY-05 | `special_industries.py` | Regulated/project revenue, price/volume, reserves/capacity, commitments and policy/commodity exposure | Official energy business evidence with period and contract/event citation | Broad code/name is not a route; missing project/contract terms stays unresolved | `test_special_industries.py`, `test_industry_route.py` |
| I-ECOM-01–I-ECOM-04 | `ecommerce_epc.py` | GMV/revenue basis, take rate, active customers/orders, fulfillment/marketing and platform evidence | Official identity plus company-level e-commerce evidence | Gross/net ambiguity, missing denominator or candidate-only route stays unresolved | `test_ecommerce_epc.py` |
| I-EPC-01–I-EPC-05 | `ecommerce_epc.py` | Binding backlog, cancellation/indexation, progress/cost estimate, contract asset collection, claims and onerous contracts | Original contract/note/KAM evidence with project and period identity | Pipeline is not backlog; missing cancellation, progress, cost or collection evidence stays unresolved | `test_ecommerce_epc.py` |
| I-FIN-01–I-FIN-04 | `financial_institutions.py` | Regulated bank, life, P&C or securities business evidence and subtype-specific regulatory/financial facts | Official identity, regulated business route, fact periods and citations | Ambiguous subtype stays blocked and never enters the general-company model; bank NIM/NPL/CET1, insurer CSM/solvency/reserve, P&C combined/loss/reserve and securities brokerage/trading/capital semantics are not mixed | `test_financial_institutions.py` |

## Real HTTP and browser acceptance — 2026-08-03

Candidate main SHA before this documentation commit: `503f5cd227ce686054c1682a061f014c03531824`.
The server used a disposable `/tmp` data root and bound only to `127.0.0.1:18890`.
No Hermes/API credentials were used.

| Issuer | Submitted path | Served contract | Actual result | Browser truthfulness | Filing store |
|---|---|---|---|---|---|
| 2330 / TWSE / issuer 22099131 | Dashboard HTTP `POST /api/analyses`, job `79797356-90b5-471b-9c8c-084f3fd07f7b`, generation `a8c906ad-8674-4c6e-95b2-6a1dc7185306` | `SingleCompanyResearchReport.v4` + `ChecklistAssessment.v1`; report/result/job generation and identity matched | core `partial`; three statements 60/60; 137 official citations; 35/103 checks evaluated | Rendered 2330/TWSE, “核心分析完成・部分外部來源未取得”, “權威詳細檢查未完成”, 8/13 completion conditions, 35/103 and manufacturing/hardware route | 0 hits, 161 misses, 144 saves, 0 corruptions on first isolated run |
| 6488 / TPEx / issuer 28113286 | Submitted through the browser form, job `a5d7960c-ae34-41fd-a4ec-4741096e567f`, generation `4f4fc717-bc95-4c06-82aa-30eedcf01e75` | `SingleCompanyResearchReport.v4` + `ChecklistAssessment.v1`; report/result/job generation and identity matched | core `partial`; three statements 60/60; 134 official citations; 38/103 checks evaluated | Rendered 6488/TPEx, “核心分析完成・部分外部來源未取得”, “權威詳細檢查未完成”, 8/13 completion conditions, 38/103 and manufacturing/hardware route | 114 hits, 46 misses, 36 saves, 0 corruptions on replay |

A prior first 6488 run correctly returned a blocked core when official requests
returned temporary 307 responses and only 42/60 statement windows were available.
After the filing-store replay, the browser-submitted run reached 60/60 and became
partial, not complete. This demonstrates that blocked, partial and detailed
unresolved states remain independent and are not promoted by job success.

## Final gate

- `python -m compileall -q src`: passed.
- Full `python -m pytest -q`: **590 passed**, four existing unknown-marker warnings.
- The real Dashboard run verified official identity → official-source collection →
  report v4/checklist v1 → `_jsonable` result file → served HTTP JSON → browser
  rendering for one TWSE and one TPEx issuer.
- Remaining unresolved checks shown in either report are real evidence gaps, not
  implementation success claims and not evidence that risk is absent.
