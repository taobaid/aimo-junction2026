# Faster general dish planning — v0.13

## What changed

Quick plan uses one Claude structured recipe-draft request, followed by catalogue
identity matching in batches of up to eight ingredients and live supplier price /
availability lookups. It skips web-search/fetch and never starts a new whole-recipe
search because an ingredient is unavailable. Empty catalogue candidate lists do
not cost additional matching calls. A later recovery quote reuses the observations
already fetched in that recovery step; final confirmation still revalidates.

Published mode retains the previous sourced-recipe workflow with its existing
source checks. Exact recipe links and pasted recipe text take priority in either
mode. Successful draft and published recipes have separate cache keys.

## Using it

1. Replace the code from this ZIP, keeping catalogue, database and environment
   settings. No new Python dependency or secret is required.
2. Restart `python aimo_api.py`, open the dashboard and press Ctrl+F5.
3. Plan a meal → **Quick plan · AI recipe draft for review**. Enter a dish,
   headcount, delivery date and preferences.
4. Review the returned recipe draft, quantities, product basket and proposed
   changes. Confirm only if suitable. Generated recipe drafts cannot auto-commit,
   even when automatic mode was selected.

Voice also defaults to quick mode in the backend without needing a Vapi tool
re-upload. The updated tool JSON exposes optional `planning_mode` for published
research. See VOICE_SETUP.md for the matching assistant wording.

Live local diagnostic, using your existing Claude and supplier credentials:

```powershell
python dish_check.py --dish "Vegetable curry" --portions 200 --date 2026-11-18 --run
```

Use a future delivery date supported by the supplier mock. Add `--published` to
research a published recipe. `recipe_client.py` also defaults to quick; the public
`POST /recipe-plans` default remains published for existing integrations. External
agents should explicitly send `"planning_mode":"quick"` to choose the fast path.

## Background jobs and limits

The dashboard posts to `POST /recipe-jobs` with an `Idempotency-Key` header and
polls `GET /recipe-jobs/{id}`. Reusing the same key and payload returns the same
job without repeating paid calls. A different payload with that key is rejected.
Jobs are authenticated and buyer-scoped, with up to four dashboard jobs queued
at once. Reopening the meal planner in the same tab resumes the job after refresh.
Run this local demo as one server process. Pending jobs from a previous process
are marked failed after restart rather than silently repeated.

`AIMO_PLANNING_SECONDS` defaults to 180 (valid range 30–600). The budget limits
new model calls, supplier-queue waits, cooldown waits and further recovery phases.
Claude timeouts are clamped to the remaining budget. HTTP read timeouts measure
inactivity, so slow streaming responses and small processing overhead can exceed
the nominal budget: this is not a hard process-termination deadline. A recipe
must exist before a partial basket can be saved; an earlier timeout returns a
clear failure instead of invented ingredients.

If a later stage reaches the budget, checked partial items and recipe quantities
are retained. Required missing items block a complete-recipe commitment. v0.15
also lets the buyer explicitly approve a partial purchase of the checked items
with all exclusions recorded. This does not claim a complete meal. Find substitutes
continues from saved ingredients instead of researching the dish again. Familiar
nonessential flavour omissions still need Yes/No approval. Included products must
still satisfy quantity, recorded dietary requirements, delivery cut-offs and stock.

## Validation and limits

171 offline tests pass. Native Claude HTTP fixtures cover eight varied dish names
and product types on the quick path: no web calls, correct scaling, real gateway
quote/stock checks and mandatory draft review. Tests also cover unknown/incomplete
recipes, fabricated source rejection, separate caches, partial-basket timeouts,
remaining-time HTTP settings, background job idempotency, auth, buyer isolation,
restart handling and failure reporting. These fixtures prove code contracts,
not the culinary quality or live latency of Claude outputs.

Browser QA confirmed quick-mode selection, prompt acknowledgement, a labelled
result, and resuming an in-flight job after refresh. No live paid Claude requests
or live supplier requests were made in this environment. Arbitrary dishes can
still lack catalogue products or have uncertain quantities; use honest recovery
choices rather than claiming guaranteed completion. No supplier orders are sent.
