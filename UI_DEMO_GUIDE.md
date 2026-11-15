# Kitchen purchasing workspace — v0.13

## Install quickly

1. Stop the running server with Ctrl+C.
2. Back up your project folder. Extract this ZIP into the existing project,
   replacing source and static files. Keep your catalogue, database, environment
   settings, Claude key and Vapi configuration. No credentials or catalogue are
   bundled in this ZIP.
3. Start `python aimo_api.py` using your existing configured terminal.
4. Open http://127.0.0.1:8000 and hard-refresh with Ctrl+F5. Reconnect using the
   reviewer token printed by this server if prompted.

## Three-minute judging walkthrough

| Challenge | Where to demonstrate it |
| --- | --- |
| Product, price and availability | Find products or the milk example; enter quantity and a valid delivery date. Compare fixed prices, availability and eligible alternatives. |
| Inquiry to commitment | Review an eligible product or meal basket, confirm the decision and show the saved mock receipt. Prices and stock are rechecked before commitment. |
| Permissions and human approval | Agent permissions shows the configured authority and next-meal control level. The 1,000 L milk example exceeds a €1,200 authority if priced at €1,770, so spending needs reviewer approval. |
| Substitution and exceptions | Open a saved blocked meal. Recognized missing seasonings offer Continue without… or Find substitutes instead. Review proposed changes with Yes/No. |
| Traceability | Open Recipe, quantities & decision history, or the product audit trail. Export the basket/evidence or mock receipt. |

Start with a saved completed basket if recipe research is still running. The
queue includes meals and direct product requests, with Review, Changes and Orders
filters plus search. Latest recipe versions appear by default; select All saved
versions for earlier attempts. The elapsed timer reports real time, not a guessed
backend completion percentage. Keep the tab open while a typed recipe is being
built; it can continue while its dialog is closed.

## Important demo boundaries

This challenge has no supplier order API. Commitments create local mock receipts;
no supplier orders or payments are sent. Approval cannot override unavailable
stock, passed cut-offs, missing quantities or failed dietary requirements.
Delivery charges and deposits are excluded from product subtotals. Mock stock
values at or above 999999 are unknown stock, not a guarantee. Use dates supported
by the fixed supplier mock schedules; changing dates cannot reset a passed cut-off.

## Verification

171 automated tests pass. Browser checks used synthetic catalogue, recipe and
supplier fixtures through the actual gateway routes: meal creation, omission
recovery, recipe confirmation, fixed-price product comparison, spending approval
and mock commitment. No paid Claude or live supplier calls were made during UI QA.

Quick plan is now the default in the meal composer and voice. It avoids web research, labels the recipe as an AI draft and requires one whole-basket review. See FAST_PLANNING.md.
