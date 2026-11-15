# Challenge coverage — Trusted Trade Agents, v0.15

## Core requirements

| Requirement | Implemented path | Demonstration |
| --- | --- | --- |
| Structured product lookup | GET /products, catalogue-wide names, recorded claims and origin, sales units | External client or Find products searches the catalogue. |
| Fixed price and availability | POST /offers, supplied mock price/availability for a shortlist | Tax-inclusive basket subtotals, cut-offs, delivery date and unknown-stock disclosure. |
| Inquiry to commitment | Offer, exact proposal, authority/approval, fresh validation, POST /orders or recipe confirmation | Local mock receipt, idempotent commitment, no supplier submission. |
| Agent authority and human approval | Separate agent/reviewer credentials, configured spending cap, fingerprint-bound decisions | Small eligible product basket can commit within authority; larger basket requires spending approval. |
| Open interface | OpenAPI and structured request/response models | External Python agent works independently of the dashboard. |

Aimo staff confirmed that the challenge has no supplier order API and producing
orders for human approval is sufficient. Commitments here create local mock
receipts. Delivery fees/deposits are excluded from product subtotals.

## Partial purchases

Any blocked dish with checked products can prepare a partial purchase. The buyer
reviews all excluded ingredients and the remaining subtotal before confirmation.
Excluded ingredients remain not supplied, and the receipt explicitly states that
it is not a complete recipe basket. This does not waive checks on included items.
The saved-recipe action makes no Claude calls. See PARTIAL_PURCHASES.md.

## Additional implemented features

- General meal request to a combined ingredient basket, with deterministic scaling,
  unit conversions, catalogue identity matching and combined-stock allocation.
- Fast AI recipe drafts for review, optional published recipe research, exact
  recipe URL ingestion and buyer-pasted complete recipes.
- Targeted compatible substitutions and broader same-ingredient alternatives.
  Supported nonessential flavour omissions offer whole-basket Yes/No approval.
- Mandatory recorded claims/origin and stock/delivery/quantity checks remain hard
  constraints. An approval cannot override them.
- UI and voice share the API. Typed jobs support polling, idempotency and refresh
  recovery. Voice remains review-only. Quick drafts always require human review.
- Evidence, source provenance, fingerprints, timestamps, decision history and
  downloadable baskets/mock receipts support a human-readable audit trail.
- Key-free, clearly labelled offline sample mode for repeatable laptop testing.
  Live mode uses the tester's own authorised credentials and official catalogue.

## Limits and optional directions

| Topic | Current boundary |
| --- | --- |
| Trust | Typed evidence, freshness and exact snapshots. Origin/labels remain supplier catalogue claims, not independently signed credentials. |
| Identity and budget | One buyer and local agent/reviewer tokens. No production SSO, cumulative budgets or independently authenticated human identity. |
| Delivery | Date/cut-off eligibility checks. No historical reliability ranking. |
| Sustainability | Catalogue labels can be exposed. No certified carbon ranking or footprint dataset integration. |
| Allergens | Recorded mandatory claims and review caveats help constrain selection. No certified allergen safety or clinical nutrition engine. |
| Inventory | Kitchen inventory deduction is not implemented. Proposed tap-water supply needs approval. |
| Proactive / standing orders | No proactive selling or recurring order drift detection. These are optional scenarios. |
| Arbitrary recipes | Live quality, catalogue coverage and latency vary. Offline fixtures do not prove any dish will complete quickly. |

## Verification

184 offline tests pass, including native Claude HTTP contracts, varied-dish
fixtures, quantity/stock/approval checks, deadline partials, job idempotency,
buyer isolation and a key-free demo process with real gateway routes.
Browser QA covers purchasing flows, job refresh recovery and sample-mode startup.
No paid/live model or supplier calls were made in this verification environment.

## Judging walkthrough

1. Start the offline demo using LAPTOP_SETUP.md, or your configured live gateway.
2. Show the 10 L milk mock receipt as the within-authority path.
3. Show 1,000 L milk at EUR 1,770 above EUR 1,200 authority. Record a reviewer
   spending decision and recheck before mock commitment.
4. Show the bolognese omission choice and its exact-basket confirmation.
5. Open the audit evidence and /docs. Explain how another agent calls the same API.
