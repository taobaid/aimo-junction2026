# Trusted Trade Agents — local purchasing API

## v0.15: continue with available items for any dish

A blocked saved meal with checked products now offers **Continue with available
items**, regardless of dish or ingredient type. This creates a fresh partial
basket, explicitly lists excluded ingredients and shows its tax-inclusive total.
**Yes, confirm partial basket** requires reviewer access and records a mock
receipt with `fulfillment_scope=SELECTED_ITEMS_ONLY` and
`complete_recipe_basket=false`. It never claims that the full recipe is supplied.

The action reuses the saved recipe and selected products. It makes no Claude
research or matching calls, and only rechecks prices/availability. Existing quick
planning, source caching, background jobs and time budgets remain in place.

After updating, restarting and Ctrl+F5, open the existing blocked lasagna plan in
Purchases (or Recent meal plans). No need to generate the recipe again. This works
only when at least one checked product can be purchased; empty purchases remain
blocked. Included products must still pass price, stock, quantity, dietary/origin
and delivery validation. See PARTIAL_PURCHASES.md. 184 offline tests pass.


## Start here: repeatable laptop demo (v0.14)

Install Python 3.11+, extract the ZIP and run **start_demo.cmd** on Windows or
`sh start_demo.sh` on macOS/Linux. Open http://127.0.0.1:8000 and paste the
reviewer token printed in the terminal. No API keys or official catalogue needed.
The first dependency install needs internet. Sample mode uses three fixed dishes
and synthetic offers through the actual gateway and resets each restart.

For live Claude and the Aimo mock APIs, use **run_live.py** with your own keys and
official catalogue. **LAPTOP_SETUP.md** covers both modes. **SUBMISSION_GUIDE.md**
maps the project submission fields and provides a short recording plan.

173 offline tests pass. CHALLENGE_COVERAGE.md now describes current capabilities
and limits without the older single-product-only statements.


## v0.13: faster general dish planning

The dashboard and voice now default to **Quick plan**: Claude proposes a complete
metric recipe draft without web-search/fetch or repeated whole-recipe research.
Every generated recipe is clearly labelled and requires reviewer confirmation.
Choose **Research a published recipe** or supply your own recipe URL/text when
that evidence is required. Prices, stock, claims and purchasing authority still
come from the existing deterministic gateway checks.

Typed planning runs as an authenticated, idempotent background job. Reopening the
meal planner after a page refresh resumes its saved job. A default 180-second
planning budget limits provider timeouts and further recovery work; checked
partial baskets are retained when a later stage runs out of time. This is a
cooperative budget, not a guaranteed wall-clock completion deadline.

See **FAST_PLANNING.md** for mode choices, configuration and verification.


## v0.12: kitchen purchasing workspace

A new unified workspace brings meal planning, product comparison and voice requests
into one dashboard. Use the searchable purchase queue to review baskets, resolve
changes and find mock receipts. The permissions view explains the configured
spending authority and lets you choose the control level for the next meal.

Basket items, quantities, availability and tax-inclusive subtotals are visible
before confirmation. Source evidence, editable recipe quantities and the audit
trail sit under a disclosure panel. Recipe changes have clear Yes/No actions and
targeted substitute/omission recovery. A live elapsed timer and duplicate-submit
protection keep long recipe requests understandable.

See **UI_DEMO_GUIDE.md** for a quick installation and judging walkthrough.
The API, approval rules and mock-only order boundary are preserved.


## v0.11: practical choices for missing seasonings

A missing Worcestershire sauce now becomes a proposed omission before expensive
alternative matching, substitution calls or another whole-recipe search. The
existing recipe stays intact with that proposed change and the buyer gets
“Order without Worcestershire sauce?” plus Yes/No and “Find substitutes instead”.
Recognised nonessential flavour additions include cooking wine (in supported
sauces/stews), Worcestershire, dried oregano/basil, ground black pepper, paprika
and Italian herb seasoning. Ingredients explicitly named in the request/preferences,
“no omissions”/“exact recipe” requests, defining dish flavours and staple ingredients
are not silently dropped. All changes still need buyer review.

### Use the basket that already finished

After replacing code, restarting and hard-refreshing, open **Plan a meal → Recent
meal plans → the existing blocked plan**. It now offers **Continue without
Worcestershire sauce** if that missing seasoning is eligible. This action uses
the saved recipe, performs fresh price/stock checks and shows a new basket for
final Yes/No. It does NOT call Claude or repeat recipe research. Keep your database
when upgrading or the old plan will not be available.

**Find substitutes instead** uses only the saved recipe and its unresolved/omitted
ingredients. It does product/substitute matching without starting another recipe
search. A proposed substitute still must pass quantity, claims, price, stock,
delivery and whole-basket checks; the resulting basket is reviewed again. A failed
substitution can return to the omission choice. Unknown amounts for staple foods
still block; a complete ingredient list remains required.

For new requests, practical handling is the default. The API option
`recovery_mode="substitutes"` explicitly requests substitute-first handling instead
of quick seasoning omissions. The source-record key distinguishes these modes.
Unknown quantities for eligible omitted seasonings no longer trigger repeated
recipe-source searches. In-request omission checks reuse the current observation
batch; final confirmation always performs fresh validation. Terminal logs now
show safe recipe stage starts/completions without keys or source text.

### Timing and verification

This fixes the wasteful exception path; it is not a promise of a universal
maximum runtime. First-time Claude web research, model matching and mock supplier
rate limits can still take time. Previously successful sources are reused under
the existing policy. The saved-plan omission action needs no model calls and
substitute lookup does not research the entire meal again.

151 offline tests pass, including immediate missing-Worcestershire proposals,
conversion of a saved blocked plan without additional model calls, substitute
selection from saved evidence, mandatory ingredients, exact-basket fingerprints,
declined plans and fresh stock failures. Browser QA verified a saved blocked
plan → omission review → substitute review → mock receipt using fixtures, not
paid live Claude/supplier calls. Keep all working environment/Vapi settings.
No production orders are sent.


## v0.10: consistent terminal, UI and voice recipe selection

Previously each request independently researched and extracted a recipe. A
successful local dish check did not establish a reusable recipe for the UI.
Different sources/extractions could produce different amounts or new unknowns.
The local diagnostic also defaults to kitchen estimates, while the UI and voice
respect their selected/enabled measurement policies.

Successful source recipes are now shared for 24 hours in the same AIMO_DB used
by the gateway, keyed by normalized dish request (ignoring a trailing “for 200
people”), portions, preferences, buyer, measurement policy, mandatory claims/
origin, provider/model and API endpoint. No API key is included in the key/payload.
A successful dish_check run seeds this recipe record; a later matching UI/voice
request uses the same source facts. Every product match, price, availability,
quantity, approval and final order validation still runs afresh. A source-cache
record is not a stock reservation, approved basket or guaranteed order.

The UI says “Using the same successful recipe” for a reuse. In “Use your own
recipe”, select “Find a new recipe” to bypass it. The CLI has --fresh. Set
AIMO_RECIPE_CACHE=0 to disable reuse. Explicit URLs and pasted recipes do not
use another request's cached recipe. Failed baskets never seed the successful
recipe store. Corrupt or expired records are ignored. Alternative recipe variants
retain their review requirement after reuse.

Source parsing now accepts explicit decorated metric amounts such as “400 g
dried spaghetti” and checked per-serving expressions such as “200 g per person
× 8”. The latter is converted to the original yield before target scaling, so
it is never multiplied twice. Conflicting counts and unknown measures stay
unresolved. Exact metric handling works in both strict and kitchen modes.

### Upgrade and verify the same recipe through the UI

Keep catalogue, database and all working environment settings. Replace code,
restart the server, hard-refresh the browser and create a new request. After
upgrading, run the successful local command once to seed the recipe record:

```powershell
python dish_check.py --dish "Spaghetti bolognese" --portions 200 --date 2026-11-18 --run
```

Use the SAME project folder/AIMO_DB, provider/model, preferences and kitchen
measurement policy as the gateway. Voice kitchen estimates require the existing
server setting AIMO_RECIPE_MEASUREMENTS=kitchen. The diagnostic uses paid API
calls but creates no order or saved proposal; it now stores successful source
facts only. It reports measurement_mode and recipe_reused in its JSON. New runs
can still fail if current supplier offers cannot meet the requirements.

Then enter “Spaghetti bolognese for 200 people”, the same date and preferences
in the UI, with Kitchen planning selected. The result should show recipe reuse.
If it does not, compare AIMO_DB/project folder, model/provider, preferences,
measurement mode and the running version before making another paid request.
Old saved blocked plans keep their old snapshot; open a new plan instead.

143 offline tests pass, including local source_meal success followed by an actual
UI API request without a second recipe search, fresh-stock failure after reuse,
policy/buyer/model isolation, expiration/tamper rejection, metric decoration and
per-person scaling. Existing native Claude request-contract and dish-ordering
tests still pass. This update was not run against the user's live credentials.


## v0.9: whole-dish sourcing and Claude regression coverage

The planner now chooses product assignments against combined SKU stock rather
than picking the cheapest product independently for every ingredient. A bounded
4096-step search seeks a feasible assignment; unresolved rows remain blockers
and enter normal alternative-offer/substitution recovery. Fresh confirmation
still checks only the exact approved SKUs and quantities.

Garlic measures such as “4 cloves of fresh garlic, peeled and finely chopped”
now use the existing opt-in kitchen clove profile. No quantity is invented if the
source contains no count; strict mode still refuses estimated weights.

Semantic matching can return up to 12 compatible offers per ingredient. Recovery
considers unselected existing candidates plus up to 40 genuinely new candidates,
instead of repeatedly retrieving the same initial products. A substitution cannot
fix its own line by breaking a previously matched ingredient’s stock allocation.

If a complete web-selected recipe cannot be sourced, at most TWO additional
published recipes for the requested dish are considered. Only an entire eligible
basket can replace the original. The recipe change is recorded with both source
URLs and requires whole-basket Yes/No even in automatic mode. Exact URL selections
and buyer-pasted recipes are never replaced this way. Research/source failures
retain the original assessment. The original selector still tries up to three
sources for quantity completeness, so total research is bounded at five attempts.

134 offline tests pass, including the native Claude HTTP adapter through source
extraction, garlic conversion, expired beef exclusion, conflicting shared stock,
source-variant fallback and fresh stock failure during final confirmation. Other
dish smoke fixtures cover salmon soup, dal, vegetable curry, tofu and apple crumble.
These are synthetic fixtures, not live recipe/supplier coverage. No live Claude
credential/catalogue was available in this environment.

### Test your live environment without creating an order

Keep your existing Aimo, catalogue and Claude settings in the terminal. Run:

```powershell
$env:RECIPE_PROVIDER = "anthropic"
python dish_check.py --dish "Spaghetti bolognese" --portions 200 --date 2026-11-18 --run
```

This uses Claude API credit and mock supplier requests. It prints the selected
recipe/source, converted amounts, chosen products and exact blockers; it creates
NO saved proposal or order. Use a currently eligible delivery date. Exit code 0
means ready for review, 2 means a genuine incomplete basket, 1 means model/config
failure. Without --run, it only explains what would be checked. Kitchen estimates
are the explicit default for this diagnostic; --strict disables them.

### Upgrade

Replace code, retain catalogue/database/environment settings, restart and create
an entirely NEW plan. Old plans keep their original evidence. Keep your working
VAPI_PUBLIC_KEY, VAPI_ASSISTANT_ID and VAPI_WEBHOOK_SECRET. For voice kitchen
estimates the server must have AIMO_RECIPE_MEASUREMENTS=kitchen. Normal UI users
can select Kitchen planning in Quantity settings. All receipts remain mock only.
Cut-offs, unknown/empty stock, mandatory claims and delivery dates are not waived;
no code can guarantee a basket if all valid offers are actually unavailable.


## v0.8.4: fix Claude schema compatibility

The 80-ingredient Pydantic bound introduced maxItems into the structured-output
schema. Claude does not support this keyword. The native Claude adapter now
removes unsupported wire constraints and keeps them as descriptions, while
Pydantic continues to enforce all bounds on returned data. Actual property
names and required fields are preserved. HTTP 400 diagnostics identify the
failed stage, and deterministic bad requests are not automatically retried.
128 offline tests pass, including a mock provider rejecting maxItems and local
rejection of 81 ingredients. No live Claude key was available for verification.
Restart and start a NEW meal request; retain all working settings.
Reference: https://platform.claude.com/docs/en/build-with-claude/structured-outputs


## v0.8.3: reveal redacted recipe failures in voice jobs

Recipe HTTP 502/503 failures now display the gateway’s specific diagnostic
(e.g. Claude timeout, provider rate limit, source extraction failure). Raw
provider bodies and unknown errors are not forwarded, and configured key/token/
secret values are redacted. This exposes the cause; it does not establish that
an unknown live upstream failure is fixed. Restart and create a NEW request;
existing failed jobs retain their saved generic message. 125 offline tests pass.
Run `python claude_check.py --search` in the server environment to diagnose
live Claude API, web-search/fetch and extraction access. Keep all working settings.


## v0.8.2: validate voice dates before announcing planning

Past delivery dates are rejected immediately in the create_recipe_plan tool
response, before any job or model work begins. The error tells the assistant
to ask for the correct future date and year. The caller can correct it within
the same call. No year is silently changed. New web calls fetch the server date
and pass it as current_date/current_year variables, plus a date-grounded opening
message. The saved assistant/provider/tools remain unchanged. 123 offline tests
pass. Restart, hard-refresh and begin a NEW call; existing jobs/calls do not change.
Keep all working keys, tokens, Vapi identifiers and webhook secret.


## v0.8.1: explain voice validation failures

Voice jobs now show the requested delivery date and server date when a delivery
date is in the past. Other HTTP 422 validation errors identify allowed field
names without exposing private upstream details. Start a NEW voice request
after upgrading; old failed jobs retain their saved message. 121 offline tests
pass from the packaged ZIP. Keep all working environment settings.


## v0.8: robust recipe selection

Request any dish, select an exact public recipe URL, or paste your own full
recipe with its original serving yield. Up to three bounded source attempts
preserve the best candidate. Recipes may contain up to 80 ingredients; matching
is batched. See **RECIPE_SELECTION.md** for behavior, examples and limits.
Keep your working catalogue, database and Aimo/Claude/Vapi environment settings.
Restart the gateway, hard-refresh the browser and create a new meal plan.


## v0.7: voice requests integrated

Choose **Speak your request** in the signed-in dashboard. The supplied Vapi
bridge now runs inside the existing server; the supplied animated orb is part
of the UI. Voice builds review-only meal baskets in background jobs and opens
the existing Yes/No review screen. See **VOICE_SETUP.md** for the required Vapi
webhook settings and **vapi_tools.json** for tool parameter schemas. No separate
bridge process is needed. Keep catalogue, database and environment settings
when replacing code. Restart the server after upgrading.


## v0.6.1: leave out unavailable cooking wine

An unavailable red/white cooking wine in bolognese, ragu, stew or tomato sauce
now becomes an explicit “Order without red wine?” proposal after checking
additional same-ingredient offers. It does not need a catalogue replacement.
Yes accepts the recipe change and revalidates the remaining basket; No cancels.
The omission is saved in the basket fingerprint and mock-order receipt.
Explicit wine preferences are not waived. Main ingredients and unresolved
quantities are not automatically dropped. This rule is deliberately limited
to cooking wine in the named dishes, rather than treating every ingredient as optional.

The result screen hides the request form, technical status codes and quantity
editors. It shows the meal, portions, date, revised total, changes and two clear
buttons. Quantity settings and ingredient evidence are collapsed; “Plan another
meal” returns to the form. Create a NEW plan after upgrading (old plans retain
their original snapshot). Keep your catalogue, database and environment settings.

Verified: 101 offline tests from the packaged ZIP, JavaScript syntax validation,
and browser confirmation of a wine-free basket using synthetic model/supplier
responses. Live Claude/supplier recovery requires your server credentials.
All order records remain mock-only; no supplier orders are sent.


## v0.6: automatic exception resolution, then Yes/No

The main meal result is now a short decision summary. The agent attempts to
resolve sourcing issues before asking you to decide, rather than sending you
straight to ingredient editors. Create a NEW meal plan after upgrading.

Recovery is enabled by default (resolve_exceptions=true):

1. Evaluate the original ingredient matches with fixed supplier prices and
   availability. If they fail, search up to 40 additional candidates for those
   same ingredients and validate the model's catalogue-only matches.
2. For remaining shortages with a known KG/L quantity basis, ask the model for
   up to three recipe-compatible replacement options per ingredient, at most
   15 options overall. Each option can contain 1–3 required replacement parts.
   Quantities are explicit same-dimension ratios between 0.001 and 5. The agent
   does not invent a quantity when the original requirement is unknown.
3. Search the actual catalogue for those replacements, match their identity and
   preparation form, and validate quantities, mandatory product claims/origin,
   prices, stock, delivery dates and cut-offs. Shared-SKU stock is checked for
   the combined basket. Every component of a replacement blend must qualify.
4. Plain cooking/tap water can be proposed as an on-site supply instead of a
   bottled-water purchase. It remains a required ingredient: your Yes confirms
   the kitchen can provide it. This rule never includes water chestnuts,
   flavoured water, bottled/mineral/sparkling water or arbitrary pantry goods.
5. If a valid complete basket is found, show what changed, quantities, caveats
   and the combined subtotal, followed by **Is this okay?**
   **Yes — approve & mock-order** accepts this exact revised basket and commits
   a local mock receipt after fresh supplier validation. **No — don’t order**
   saves REJECTED and cannot later be overridden by Yes for that same plan.

Any alternate-offer recovery, ingredient substitution or kitchen-water proposal
requires one reviewer Yes/No, including requests in automatic mode and baskets
within the automatic limit. An agent token cannot approve its own substitutions.
Unchanged fully eligible baskets can still follow previously granted authority.
Accepted changes and assumptions are retained in the fingerprint and mock receipt.

Original recipe evidence, ingredient details, optional quantity editors and the
recovery trace remain available under **Recipe, ingredients and decision evidence**.
Garlic parsing also accepts heads/bulbs (a labelled 24 g reference estimate), size
words on cloves, trailing preparation and source-supplied metric equivalents.

The model must preserve the requested dish and preferences, and describe flavour
or potential new-allergen differences. These are proposed recipe adaptations,
not independently certified allergen safety or nutritional equivalence. Buyer
mandatory claim/origin rules are still checked against each selected product;
price, availability, cut-offs and unknown quantities cannot be waived by Yes.
The recovery is a bounded attempt, not a guarantee that every synthetic stock
scenario can be fulfilled. If none of the checked options forms a valid whole
basket, no partial order is committed and the result says it cannot complete it.
A failure of optional recovery retains the last assessed basket, without falsely
accepting an unvalidated substitute. No supplier order is ever submitted.

API additions: RecipeRequest.resolve_exceptions defaults to true; RecipePlanView
includes changes and resolution_attempts; POST /recipe-plans/{id}/decline is
reviewer-only and requires the exact saved fingerprint. Set resolve_exceptions=false
in an API request to retain the original recipe without automatic recovery.

Upgrade: stop the server, replace code from this ZIP, keep the product catalogue
and SQLite database, restart with the existing Claude/Valio environment settings,
then create a new meal plan. No new Python dependencies are required.
98 offline tests pass, including the stock-out → substitutes → Yes/No flow,
No/idempotency, fresh stock changes, hard claims and aggregate stock for blends.
The browser flow was verified with synthetic model/catalogue/supplier fixtures.
Live model substitutions against your actual mock data remain to be verified
with your private key. Recovery adds model and supplier calls, so it can take
longer and uses additional model credits; supplier 429 handling is unchanged.


## v0.5: fewer manual ingredient decisions

The recipe agent now normalises ordinary recipe measures before catalogue
matching. In **Plan a meal**, select **Kitchen planning: allow the listed
ingredient estimates** (the reviewer UI default), choose your control mode,
and create a NEW meal plan. Resolved quantities no longer require a separate
manual ingredient entry. Optional quantity editors start collapsed.

- Exact units: metric weights/volumes, pounds, weight ounces, fractions and
  measured multipacks such as `12 cans x 29 oz each`. Weight ounces are never
  treated as fluid ounces. For a 100-serving source scaled to 200, these cans
  require 19.731268095 kg of sauce, before sales-pack rounding.
- Kitchen estimates: named profiles for fresh chopped/diced onion, raw garlic
  cloves, minced garlic, table salt, granulated sugar, dried basil/oregano leaves,
  tomato paste and vegetable oil. Quantities are marked with an approximate sign,
  with the factor and reference link beside each ingredient. Profiles assume
  US household proportions and edible food quantities; packing, preparation,
  peeling loss and actual product density can differ.
- An Italian dry-herb blend has only a clearly labelled **demo proxy** of 1 g/tsp,
  not an independently verified supplier density. It always requires one
  whole-basket reviewer decision, even if all costs are within authority.
- Precise mode still performs exact weight conversions but does not use these
  kitchen estimates. Unsupported ingredients, missing can sizes, ambiguous
  measures and “to taste” stay unresolved. No ingredients are silently omitted.
- If required quantities cannot be resolved under the selected policy, the
  agent researches one alternative recipe and keeps the complete source with
  better resolvable-quantity coverage. It never merges two recipes or drops
  troublesome ingredients. Informational notes no longer force spending review;
  substantive review_reasons, uncertain matches and user preferences still do.
- Catalogue search now runs for unresolved required ingredients too, so an
  unknown quantity no longer produces the misleading impression that the
  ingredient was never available in the catalogue. Pricing waits for a quantity.

Buyer authority is enforced server-side. A reviewer can opt into Kitchen planning
for a request. An external agent cannot enable it for itself; the buyer must set:

```powershell
$env:AIMO_RECIPE_MEASUREMENTS = "kitchen"
```

For autonomous mock commitment, the existing AIMO_RECIPE_AUTONOMY=automatic
setting is also required for an agent. Normal budget, stock, cutoff, product
claims/origin and fingerprint checks still apply. Revoking kitchen authority
blocks agent commitment of an existing estimate-based plan pending reviewer
approval. Saved plans and receipts retain quantity assumptions and references.
One approval covers the entire recipe basket, not each ingredient separately.

External meal client: add `--kitchen-estimates` to `recipe_client.py` when the
buyer has enabled this policy. GET /recipe-measures exposes versioned profiles
and agent eligibility. POST /recipe-plans accepts measurement_mode=strict|kitchen.

Upgrade: stop the server, replace code from this ZIP, keep the catalogue and
SQLite database, restart with your existing Claude and Valio key settings, and
create a new recipe plan. No extra dependencies are required.

Validation: 88 offline tests, including all nine previously unresolved screenshot
items, buyer permission/revocation, whole-basket approval and mock commitment.
The browser flow was checked with synthetic recipe/model/supplier fixtures.
No live Claude call was made without your private key, and real mock availability
can still block an otherwise correctly calculated basket.

Conversion references (stored alongside each applicable rule):
- NIST Handbook 133 Appendix E: exact weight and US/imperial volume factors.
  https://www.nist.gov/system/files/documents/2025/12/23/2026_NIST_HB133_AppendixE-20251222.pdf
- King Arthur Ingredient Weight Chart: ingredient-specific reference weights.
  https://www.kingarthurbaking.com/learn/ingredient-weight-chart
- Health Canada CNF 2394: raw garlic clove reference weight.
  https://food-nutrition.canada.ca/cnf-fce/serving-portion?id=2394
- USDA SR28, foods 02003 and 02027: dried basil and oregano leaf teaspoon weights.
  https://www.ars.usda.gov/ARSUserFiles/80400525/Data/SR/SR28/reports/sr28fg02.pdf
The herb-blend demo proxy has no supplier-density reference and is labelled so.


## v0.4.4: diagnose Claude connection failures

The old “Could not reach Claude or parse its response” message hid several
different failures. Errors now name the stage (research, extraction or matching)
and distinguish read timeout, connection timeout, DNS/TLS/proxy connection
failure, other transport failures, non-JSON gateway pages and invalid JSON shape.
Raw exception text and provider bodies are not printed. Uncertain paid requests
are not automatically repeated. A read timeout does not establish bad credentials.

Stop the server, replace the code from this ZIP, keep your existing environment
settings, catalogue and database, then run this in the SAME PowerShell terminal:

```powershell
python claude_check.py
```

This sends one short message with a 32-token output limit, consumes a small
amount of API credit, and prints PASS or a redacted failure. It does not call
Valio, create a plan or order anything. PASS verifies a completed short model
request, not web-search/fetch access. To test the recipe research separately:

```powershell
python claude_check.py --search
```

The --search test can make multiple model/search/fetch calls, consumes credits
and can take several minutes; it still does not price products or save orders.
For a local read timeout, the default wait is now 300 seconds per provider
request. You can set 30–600 seconds without changing the 20-second connection
timeout; for example:

```powershell
$env:ANTHROPIC_READ_TIMEOUT = "600"
python aimo_api.py
```

Longer timeouts do not fix blocked connections or provider/network outages.
The CLI and dashboard now give evidence to distinguish those cases. Tests are
offline; live API access on your computer remains to be verified.
75 automated tests pass, including injected network failures and diagnostic use.

## v0.4.3: complete recipes and visible supplied quantities

Claude recipe research now opens the full source page with web_fetch_20250910
(up to two page fetches per research attempt), instead of accepting source URLs
from snippets alone. The extractor must explicitly assess ingredient-list
completeness and name any missing parts. If incomplete, one fresh research and
extraction attempt is made automatically. If still incomplete, the plan is saved
as BLOCKED without product matching/pricing; no partial recipe can be committed.
Older uncommitted recipes without this assessment require a new plan. Full-page
retrieval and model assessment improve evidence but are not independent recipe
certification. A fetch failure or missing accessible page may still stop research.

Single explicit metric amounts such as “500 g” are checked against the extracted
KG/L quantity before scaling. A conflicting “500 KG” is unresolved until corrected;
complex measures, counts and densities are not guessed. Each basket line displays
required mass/volume, supplied mass/volume and amount per sales unit. For example,
SKU 460510 has structured 5 kg per BAG; its “3x” display name does not change the
actual sales unit into a 15 kg case. 100 BAG would supply 500 kg.

Unavailable meat and expired mock cut-offs still block readiness. Rebuilding
does not reset the supplier clock or clear sales blocks. Use another eligible
product/date, or ask mentors for a currently orderable mock scenario.
Stop the server, replace project code, keep the catalogue/database, restart with
the same environment settings, and create a NEW meal plan. Old incomplete plans
cannot be repaired by editing only their visible ingredient quantities.
69 offline tests pass. Live provider output remains to be checked with your key.

## v0.4.2: recipe validation fix

Fixed a schema formatter bug that removed the actual recipe `title` field when
stripping JSON Schema annotations. The provider schema now preserves every model
field, including fields named `title` or `default`, and nested definitions.
Validation errors identify the failing stage and fields without printing raw
model output. Stop the server, replace the code from this ZIP, and restart with
your existing Claude and Valio key settings. Keep your catalogue and database.
61 offline tests pass, including schema-constrained provider response regression
tests; no live model request was made without your key.

## Use your Junction Claude API credits (v0.4.1)

The recipe planner now supports Anthropic's native Claude Messages API.
You do not need an OpenAI key for this path. Redeem the challenge's Claude API
credits, then create a **Claude Console API key in the credited workspace** at
https://platform.claude.com/settings/keys. A Claude chat subscription or login
is not an API key. Never send the secret to anyone or put it in browser code.

Stop the gateway with Ctrl+C, extract this ZIP over the existing project, and
keep the catalogue and purchase_proposals.sqlite3. In the **SERVER PowerShell
terminal**, keep your working AIMO_API_KEY set and run:

```powershell
$env:RECIPE_PROVIDER = "anthropic"
$env:ANTHROPIC_API_KEY = "PASTE_YOUR_ACTUAL_CLAUDE_API_KEY"
$env:RECIPE_MODEL = "claude-sonnet-4-6"
python aimo_api.py
```

The displayed key string is a placeholder: replace it with your actual secret.
The model name above is a real supported model ID, not a placeholder.
If the console requires an explicit workspace for your key, also set
ANTHROPIC_WORKSPACE_ID to the credited workspace ID. No additional Python SDK
is required: the adapter uses the existing httpx dependency.

Reconnect to http://127.0.0.1:8000 using the newly printed reviewer token.
Click **Plan a meal**, enter the recipe request, portions and delivery date,
then **Find recipe & build basket**. Review the cited recipe and whole basket,
or choose the existing automatic mode within buyer authority. The external
`recipe_client.py` works with this same server configuration; it only needs
an AIMO_AGENT_TOKEN, not the Claude secret.

### Claude implementation and failure handling

- Uses https://api.anthropic.com/v1/messages with the native x-api-key header.
- Searches with web_search_20250305, with a maximum three searches and three
  bounded continuation requests per search stage. Only successfully fetched recipe page URLs are eligible as source evidence;
  a memory-only or snippet-only answer is rejected.
- Performs recipe extraction and catalogue matching in separate schema-constrained
  JSON calls using output_config.format. Search citations and strict JSON are
  deliberately not requested in the same message.
- Resumes pause_turn responses with their original search content blocks.
  Refusals, token truncation, tool errors (including HTTP 200 search errors),
  malformed output and missing sources stop the plan rather than inventing facts.
- Credential/credit/model/search failures produce redacted setup messages.
  No API keys are included in browser responses, saved baskets or audit events.
- All existing unit, quantity, availability, whole-basket budget, fingerprint,
  approval and fresh-validation checks apply. Mock orders are never submitted.

Each complete meal normally makes three model calls: search/fetch, extraction and SKU matching. An incomplete first source can cause a second research/extraction pair.
Search pauses may require additional bounded calls. Provider token/search charges
apply against the account associated with your key; inspect the Claude Console
for credit coverage and usage. No live Claude request was made during development
without your private key. All 98 automated tests run offline with synthetic data.

Provider selection: RECIPE_PROVIDER=anthropic (or claude) is explicit. Without
RECIPE_PROVIDER, an existing ANTHROPIC_API_KEY selects Claude automatically;
otherwise OpenAI remains the default. Claude defaults to claude-sonnet-4-6,
with RECIPE_MODEL overriding ANTHROPIC_MODEL. Existing LLM_MODEL/LLM_BASE_URL
settings are ignored for the Claude recipe adapter. Use
RECIPE_PROVIDER=openai to retain the original OpenAI recipe path.

The optional older `llm_agent.py` Chat Completions client remains OpenAI-compatible;
for Claude-backed meal requests, use the dashboard or `recipe_client.py`.
Run `python -m unittest test_api test_recipe_agent test_claude_recipe` to verify.

Official adapter references:
https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
https://platform.claude.com/docs/en/build-with-claude/structured-outputs
https://platform.claude.com/docs/en/api/overview


## Recipe requests (v0.4)

Use **Plan a meal** to enter a request such as “Spaghetti bolognese for 200 people”.
Enter **200** in the portions field (this is the authoritative scaling count), choose
a delivery date and select review-first or automatic mode. The agent searches
the web for a published recipe, extracts its source yield and ingredients,
scales the quantities in Python and matches ingredients to catalogue products.
Fixed mock prices and availability produce ONE combined basket.

### Alternative: configure OpenAI recipe AI in the SERVER PowerShell terminal

Stop the gateway with Ctrl+C. Keep AIMO_API_KEY set to the working Valio mock key.
Add a separate model-provider key and a Responses model that supports both web
search and structured outputs:

```powershell
$env:LLM_API_KEY = "YOUR_ACTUAL_MODEL_PROVIDER_KEY"
$env:LLM_MODEL = "YOUR_RESPONSES_WEB_SEARCH_CAPABLE_MODEL"
python aimo_api.py
```

The Valio API key authenticates supplier lookups; it cannot run the recipe model.
Keep model credentials on the server. No key is sent to the browser.
The default provider URL is https://api.openai.com/v1. If you already use a
Chat Completions-only LLM_BASE_URL/model, set RECIPE_BASE_URL and RECIPE_MODEL
separately to a provider/model supporting Responses + web_search + JSON schema.
The app reports configuration errors and never substitutes a canned recipe.
This feature makes provider calls when requested; provider usage charges may apply.

Reconnect using the current reviewer token, then **Plan a meal**. Review the
source link, scaled quantities, selected products, pack counts and combined total.
**Approve whole recipe & mock-order** creates a local mock receipt after fresh
validation. Nothing is submitted to Valio. Recent meal plans are saved in the
same SQLite database and remain accessible from this dialog.

### Autonomy and external agents

Review-first is the default. A reviewer may choose automatic mode for a request.
For agent-token requests, the buyer must explicitly configure this in the server:

```powershell
$env:AIMO_RECIPE_AUTONOMY = "automatic"
```

The configured AIMO_APPROVAL_LIMIT applies to the **combined product subtotal
INCLUDING tax**, never to each ingredient separately. Automatic mock commitment
requires all required ingredients resolved, eligible current offers, no flagged
recipe/match uncertainty and a subtotal within that limit. Free-text preferences
force review; they are not a certified allergy or nutrition rule engine.
Server AIMO_REQUIRED_CLAIMS and AIMO_REQUIRED_ORIGIN still apply to every product.
A restaurant can review or edit ingredient quantities; a cafeteria can delegate
the recipe choice within this authority.

External-agent example (separate PowerShell terminal, actual running agent token):

```powershell
$env:AIMO_AGENT_TOKEN = "ACTUAL_TOKEN_FROM_RUNNING_SERVER"
python recipe_client.py "Spaghetti bolognese for 200 people" --portions 200 --date 2026-11-16
# Add --automatic only when the buyer has enabled recipe autonomy on the server.
```

Structured endpoints: GET /recipe-capabilities; POST/GET /recipe-plans;
GET /recipe-plans/{id}; POST /recipe-plans/{id}/approve-and-commit (reviewer);
POST /recipe-plans/{id}/commit (already authorised);
POST /recipe-plans/{id}/rebuild (reviewer-supplied total quantities).
The generated OpenAPI contract documents request and response schemas.
Decision requests require the exact saved fingerprint. Rebuild makes a new plan,
preserving the old evidence. Quotes expire after 30 minutes. Commitment refreshes
prices/stock, rejects commercial changes and is idempotent for the plan.

### Honest limits and corrections

Missing yield, quantities such as “to taste”, unverified piece counts, unsuitable
matches or unavailable products block the WHOLE basket. Reviewers can supply
explicit total KG/L quantities in the ingredient cards and rebuild. Catalogue ST
means a packaging unit and does not prove one individual onion or egg. No weight
is guessed from a name or from gross shipping weight. Optional ingredients are
listed but excluded explicitly. Kitchen inventory is not connected, so all
required ingredients are assumed needed.

The agent uses a sourced recipe but its extraction and matching remain model
judgements; URLs are checked against returned search sources, not independently
certified. The cheapest eligible SKU is selected among up to five model-matched
options from the first 20 lexical/convertible catalogue candidates per ingredient.
This is not a global basket optimiser. Delivery charges/deposits are excluded.
No nutrition/school-meal compliance is asserted.

Offline tests use synthetic provider/search responses and mocked supplier calls.
A real model-provider request has not been tested without your configured key.
Run `python -m unittest test_api test_recipe_agent` for the regression checks.


## Reviewer dashboard (new)

Open **http://127.0.0.1:8000/** after starting `python aimo_api.py`.
Paste the actual **AIMO_REVIEWER_TOKEN** from the server terminal into the
Reviewer token field, then click **Open review workspace**.

The dashboard provides a proposal queue, basket amounts, spending threshold,
unknown-stock notice, comparison alternatives and decision history. Select a
proposal, click **Approve spending** or **Reject**, review the confirmation and
submit. Rejection requires a reason. Decisions use the exact saved fingerprint;
the browser does not calculate or submit its own price or spending limit.

Use **New comparison** to choose a product query, quantity, unit and delivery date, compare options
and save an eligible basket without using Swagger. The existing agent client
continues to work. Alternatives are the original stored comparison, not newly
fetched prices. Legacy proposals without linked comparisons say so explicitly.

Tokens stay in tab memory and are cleared on disconnect/reload. No tokens are
stored in browser local/session storage. Connecting with an agent token gives
read access but does not enable approval/rejection. HTTP 403 is also enforced by
the backend. The dashboard refreshes the queue once a minute while visible and
provides a manual Refresh button. An expired pending proposal cannot be approved.

### Upgrade from the earlier API ZIP

Stop the server with Ctrl+C. Extract this ZIP into the **same project folder**,
replacing its code files and adding the entire `static` folder. Do not delete
`purchase_proposals.sqlite3` or the product catalogue. No database is included in
the ZIP, so your saved proposals and history remain intact. The backend adds a
small comparison-link table automatically; no manual database migration is
needed.

Restart with `python aimo_api.py` in the terminal where AIMO_API_KEY is set.
Generated local tokens change on restart; use the newly printed reviewer token.
The dashboard and API use the same local database.

A working Python HTTP gateway around the milk purchasing flow. It searches the
supplied static catalogue, queries the supplied price and availability APIs,
calculates single-product baskets across the catalogue and saves an order draft, automatically authorised within policy or pending human approval above the limit. It never submits
supplier orders, connects to the production webshop or requires webshop credentials.

## Windows quick start

1. Extract this ZIP into a folder containing
   `valio_aimo_junction26_product_data.json`. All `.py` files should be beside it.
   Keep your existing `milk_compare.py`; this package uses `aimo_core.py` instead.
2. Open PowerShell in that folder and install dependencies:

```powershell
python -m pip install -r requirements.txt
```

3. Set the **Valio mock API key**, then start the server:

```powershell
$env:AIMO_API_KEY = "YOUR_VALIO_MOCK_API_KEY"
python aimo_api.py
```

The server prints two generated local tokens:

- `AIMO_AGENT_TOKEN`: search, compare, create/read proposals.
- `AIMO_REVIEWER_TOKEN`: those operations plus approve/reject.

These are different from the Valio API key. Keep the reviewer token away from the
agent. The generated tokens change when you restart the server. To use stable
tokens, set distinct values in those two environment variables before starting.

Open **http://127.0.0.1:8000/docs** to use the interactive API documentation.
The machine-readable contract is **http://127.0.0.1:8000/openapi.json**.
The ZIP also includes a generated `gateway_openapi.json` contract.

If your catalogue is elsewhere, set its path before starting:

```powershell
$env:AIMO_CATALOG = "C:\Users\torre\Downloads\juncttion2026\valio_aimo_junction26_product_data.json"
```

## Run the separate purchasing client

Keep the server terminal running. Open a **second PowerShell window**, navigate
to the same folder and copy the agent token printed by the server:

```powershell
$env:AIMO_AGENT_TOKEN = "COPY_THE_GENERATED_AGENT_TOKEN"
python agent_client.py --date 2026-11-16 --litres 1000
```

The deterministic reference client:

1. Searches for plain lactose-free milk.
2. Checks prices and availability for the shortlist.
3. Chooses the lowest tax-inclusive product subtotal among baskets passing checks.
4. Saves a proposal and prints its ID, spending state and full fingerprint.

This client is deterministic. The optional `llm_agent.py` below adds a separate
natural-language LLM tool client using the same documented gateway operations. Repeated client runs create new proposals; the local mock commitment is idempotent per proposal. Replaying a commitment
returns its existing receipt rather than creating another order.

## Review and approve in the API docs

1. Open `/docs`, click **Authorize**, paste the **reviewer token only**, and
   click Authorize. Do not prepend `Bearer`; the UI handles it.
2. Expand `GET /proposals/{pid}`, select **Try it out**, enter the proposal ID,
   and execute. Read the basket, reasons, unknown-stock warning and expiry.
3. Copy the complete 64-character `fingerprint` from the response.
4. Expand `POST /proposals/{pid}/approve`, enter the ID and use:

```json
{
  "fingerprint": "COPY_THE_FULL_64_CHARACTER_FINGERPRINT",
  "note": "Budget approved for this basket"
}
```

5. Execute. The response should show `spending_status: APPROVED` and an approval
   event. `order_submitted` remains false.

For rejection use `/proposals/{pid}/reject` with the same fingerprint and a
non-empty explanation in `note`. Agent tokens receive HTTP 403 on both routes.
The fingerprint binds the decision to the exact saved basket/evidence. It is not
a digital signature or protection from an administrator editing the database.

## API endpoints

| Method | Path | Purpose | Credential |
| --- | --- | --- | --- |
| GET | `/health` | Local server health | None |
| GET | `/policy` | Read configured buyer rules | Agent or reviewer |
| GET | `/products?q=milk&plain_milk=true` | Search static product information | Agent or reviewer |
| POST | `/offers` | Check product baskets against requirements, price, availability and policy | Agent or reviewer |
| POST | `/proposals` | Save one basket from a server-stored offer | Agent or reviewer |
| GET | `/proposals` | List this buyer's saved proposals | Agent or reviewer |
| GET | `/proposals/{pid}` | Inspect basket and event history | Agent or reviewer |
| POST | `/proposals/{pid}/approve` | Approve spending for exact fingerprint | Reviewer only |
| POST | `/proposals/{pid}/reject` | Reject with reason | Reviewer only |

Example `/offers` request:

```json
{
  "delivery_date": "2026-11-16",
  "litres": "1000",
  "product_ids": ["464201", "464073"]
}
```

Example `/proposals` request (use an actual offer ID):

```json
{
  "offer_id": "O-COPY_FROM_OFFER_RESPONSE",
  "sku": "464201"
}
```

Money and computed quantities are JSON **strings** to preserve decimal precision.
Amounts are EUR. `net` excludes tax; `gross` includes tax. The server evaluates
the spending threshold against `gross`, excluding delivery charges and deposits.
Agents cannot supply prices, a customer ID or approval limits in these requests.
Extra request fields are rejected. Missing catalogue litre/kilogram conversions are not
guessed from the product name or comparison price.

## Server configuration

| Variable | Default / purpose |
| --- | --- |
| `AIMO_API_KEY` | Required Valio mock backend key; server only |
| `AIMO_AGENT_TOKEN` | Generated on `python aimo_api.py` startup if absent |
| `AIMO_REVIEWER_TOKEN` | Separate generated reviewer token |
| `AIMO_REVIEWER_NAME` | `local-reviewer`; recorded as the decision actor |
| `AIMO_CUSTOMER` | `123`; one configured buyer per server |
| `AIMO_APPROVAL_LIMIT` | `1200`; EUR product subtotal including tax |
| `AIMO_CATALOG` | Product JSON beside the scripts |
| `AIMO_DB` | `purchase_proposals.sqlite3` beside the scripts |

SQLite stores offers, immutable proposal snapshots and decision events. Existing
CLI proposals in the same database remain readable. Old snapshots are not
rewritten to apply new rules. Proposals and offers have local 30-minute review
windows; these are not supplier reservations or price locks.

The upstream API client paces requests to one per second in this process. On
HTTP 429 it waits at least 30 seconds (longer when Retry-After requests it), then
retries up to three attempts total. Avoid multiple independent server instances
or stress-test scripts, which do not share this in-memory cooldown.

## Mentor rules applied

- Stock amounts >=999999: orderable with stock quantity **unknown**, not unlimited
  or guaranteed physical stock.
- Empty availability schedules: unavailable.
- Product/schedule sales blocks: blocked.
- Lot size 0.01: interpreted as one whole sales unit.
- Closing time: checked against its related available date; an expired cutoff
  still blocks the candidate. Fixed weekend mock dates are not silently moved.
- The challenge ends at a saved proposal for approval. There is no order API.

## Tests and limits

```powershell
python -m unittest -v test_api
```

Thirty-one integration tests use local fixtures, not live upstream calls. They cover
search/auth/schema, policy/price injection, unknown-stock baskets, approvals,
reviewer-only permissions, duplicate decisions, changed fingerprints, rejection,
blocked stock, expiry, policy changes, buyer scoping, dashboard assets, session
roles, original-comparison linkage, general quantities, automatic authority,
required claims/origin, variable-weight rejection and a mocked LLM tool loop.

This is a local prototype bound to 127.0.0.1, with one buyer and a shared reviewer
credential. It does not verify an employee's identity, implement SSO, provide
multi-tenant administration, or make stock/delivery guarantees. The spending
limit is demo configuration rather than an authenticated policy administration
service. Approval is a spending decision, not permission to bypass product or
delivery restrictions. The catalogue and all upstream data are challenge-only
synthetic data. No credentials or datasets are included in this package.


## Core challenge coverage and new request types

See `CHALLENGE_COVERAGE.md` for the requirement mapping and a focused demo plan.

The gateway now accepts `quantity`, `unit` (`L`, `KG`, `SALES_UNIT`), a `query`,
`required_claims` and `required_origin`. The legacy `litres` request field still
works. Do not supply both `litres` and `quantity`. For non-milk queries set
`plain_milk` to false (or omit it when a query/product ID list is present).

For example, compare macaroni in kilograms:

```json
{
  "query": "macaroni",
  "quantity": "100",
  "unit": "KG",
  "delivery_date": "2026-11-16",
  "plain_milk": false,
  "required_origin": "fi"
}
```

Or request two complete sales units of matching catalogue products:

```powershell
python agent_client.py --date 2026-11-16 --query macaroni --quantity 2 --unit SALES_UNIT
```

`KG` uses explicit net weight and the catalogue packaging hierarchy. Variable
weight or missing conversions remain unresolved. `SALES_UNIT` requires no litre
or kilogram conversion; inspect each returned unit/pack definition before using
it. Search is a lexical catalogue shortlist, not a guarantee that all matching
products are interchangeable. Narrow requests and inspect alternatives.

Required claim codes must be explicitly present in the product's nutritional
claims. Missing claims block the candidate. These are not a comprehensive food
safety or allergen certification system. Origin requirements use the catalogue's
countryOfOrigin field. The model must ask for clarification when requirements
cannot be expressed or verified; it must not invent claims from a product name.

Optional server-enforced product requirements:

```powershell
$env:AIMO_REQUIRED_CLAIMS = "FREE_FROM_LACTOSE"
$env:AIMO_REQUIRED_ORIGIN = "fi"
```

These apply to all requests for this buyer and cannot be loosened by an agent.
Leave unset for a general-purpose buyer. To clear a requirement in PowerShell:
`Remove-Item Env:AIMO_REQUIRED_CLAIMS` (and similarly for origin). Restart after
changing configuration.

A saved eligible basket at or below the spending limit gets
`AUTO_AUTHORISED` and an automatic-authority audit event. Above the limit it gets
`PENDING`; only the reviewer token can approve/reject it. The limit is **per
proposal**, not a daily aggregate budget. The mentor guidance allows stopping at a human-approved draft. This version
also supports a clearly labelled local mock commitment and receipt so the full
inquiry-to-commitment interaction is demonstrable. No upstream order endpoint
exists and this service never uses the production webshop.

Download that exact draft with `GET /proposals/{pid}/order-draft`, or the
**Download structured order draft** button in the dashboard. The JSON includes
its lines, recorded spending state, fingerprint, source evidence and unknown
stock disclosure. It remains explicit that delivery charges/deposits are omitted
and no order has been sent. The current review-window expiry is included.

## Optional LLM purchasing agent

This is separate from the gateway. The gateway works without a model or model
key. The LLM client uses the Chat Completions function-tool protocol and obtains
its offer/request schemas from the gateway's OpenAPI contract. Official protocol
reference: https://developers.openai.com/api/docs/guides/function-calling

In the **client terminal**, set your actual agent token, a model-provider API key
and a model identifier supporting Chat Completions function tools:

```powershell
$env:AIMO_AGENT_TOKEN = "YOUR_ACTUAL_LOCAL_AGENT_TOKEN"
$env:LLM_API_KEY = "YOUR_MODEL_PROVIDER_API_KEY"
$env:LLM_MODEL = "YOUR_TOOL_CAPABLE_MODEL_ID"
python llm_agent.py "I need 1000 litres of plain lactose-free milk by Monday. Find the cheapest eligible option and create a proposal."
```

`LLM_BASE_URL` defaults to `https://api.openai.com/v1`. Set it to another
compatible provider if desired. Compatibility depends on that provider/model;
only the protocol loop with a mocked provider is tested here. No live model call
has been made during development. Use your own model credentials; the Valio
challenge key cannot authenticate to a model provider.

The LLM sees the user request and synthetic gateway tool results, not either
service credential. It has five tools: read policy, search products, compare
offers, create a proposal and place a local mock order. It refuses to run with a reviewer credential and
has no approve/reject or arbitrary-HTTP tool. It creates at most one proposal, can commit that proposal when authorised, and
limits tool rounds. Exact claims, quantity arithmetic, stock/delivery checks,
prices, role checks and spending authority are enforced by server code. Natural
language interpretation itself remains model behaviour and needs a live demo
check with your chosen model. Clarification is preferable to silently weakening
requirements.

A reliable model-free demo of the two authority branches is:

```powershell
python agent_client.py --date 2026-11-16 --litres 100
python agent_client.py --date 2026-11-16 --litres 1000
```

With the currently observed prices and EUR 1200 limit, 100 litres should be
within authority and 1000 litres should need approval. Actual eligibility still
depends on the mock cut-off and delivery responses. No dates are silently shifted.


## Complete inquiry → commitment flow (version 0.3)

The three core tasks now have concrete endpoints:

| Task | Operations |
| --- | --- |
| Product/price/availability lookup | `GET /products`, `POST /offers` |
| Fixed-price inquiry to commitment | `POST /proposals`, `POST /orders`, `GET /orders/{id}` |
| Permissions and human approval | `GET /policy`, automatic authority evaluation, reviewer-only approve/reject |

`POST /orders` commits a **LOCAL MOCK ORDER**, not a supplier order. It rechecks
current price, quantity conversion, dietary/origin requirements, availability,
cut-off, delivery date, expiry and spending authority. An unapproved pending
proposal cannot be committed. Any commercial change returns HTTP 409 and requires
a new proposal/authority decision. Stock-marker values remain explicitly unknown
but orderable under the mentor's mock rules. Delivery fees and deposits are not
part of this simulated product subtotal.

The request is only:

```json
{"proposal_id": "P-YOUR_ACTUAL_PROPOSAL_ID"}
```

The receipt contains an `M-...` ID, `status: COMMITTED_MOCK`, the approved
fingerprint, fresh validation evidence and `upstream_order_submitted: false`.
Exactly one receipt can be stored per proposal. Retrying the same commitment
returns HTTP 200 with the same receipt; initial creation returns HTTP 201.
Receipt creation and the commitment audit event are one database transaction.
`GET /orders` lists saved receipts for the configured buyer.

### From the dashboard

Review a pending proposal and approve it. The action bar then offers
**Commit mock order**. Confirm that action to perform fresh checks and save the
local receipt. An auto-authorised proposal offers this action immediately.
After commitment, download the mock receipt from the same action bar. Existing
proposals and history stay in the database; very old proposals without recorded
requirements/evidence must be recreated before mock commitment.

### From the external client

The reference client now automatically commits a newly created proposal if it
is within authority. To stop at a proposal, add `--draft-only`:

```powershell
python agent_client.py --date 2026-11-16 --litres 100
python agent_client.py --date 2026-11-16 --litres 1000
```

The larger request normally requires review. After the reviewer approves it:

```powershell
python agent_client.py --commit-proposal P-YOUR_ACTUAL_PROPOSAL_ID
```

An expired proposal or changed offer must be recreated and reapproved rather than
reusing old authority. No real payment, production order, stock reservation or
delivery guarantee is made by this prototype. A production adapter would require
Valio's actual order interface and complete delivery/deposit cost handling.

The 31 tests also cover pending-order denial, automatic commitment, reviewed
commitment, same-receipt retries, changed-price refusal, new stock/claim failure,
policy/expiry/buyer checks and atomic receipt/audit persistence.


## Version 0.3.1 — avoiding empty/unorderable shortlists

Catalogue query searches now prioritise products with supported conversions for
L/KG. They query dynamic data in batches of at most 20, continuing past the first
batch when fewer than five eligible options are found (at most 60 candidates per
comparison). The response reports match/conversion/checked/eligible counts and a
`next_scan_offset` when more compatible candidates remain. Use the dashboard's
**Check more matching products** or pass that offset in the next `/offers`
request with the same criteria. Explicit SKU requests still show those SKUs,
including unresolved ones, rather than silently substituting other products.

The dashboard puts eligible choices first, with blocked/unresolved results in a
separate expandable section. It shows per-sales-unit prices when a physical
basket cannot be calculated. **Use sales units instead** changes the unit only
when clicked and clears the old quantity: enter a new pack/case count yourself.
It never reinterprets 100 kilograms as 100 packs automatically.

Case-level net weights can now be used when the CASE record, sales-unit GTIN and
labelled multipack count agree with the unit hierarchy. The case weight is NOT
multiplied by the pack count a second time. Gross weight is never used as net
food weight, and a weight is never invented from the product name. Records with
insufficient evidence remain unresolved in KG/L; use sales units explicitly if
that meets the buying need.

A passed order cut-off and unavailable stock remain genuine blockers. Changing
units does not override them. Choose another eligible product or try a later
delivery date; fixed mock dates may still make a particular SKU unavailable.
Product searches now match whole words, avoiding e.g. `pasta` matching a Finnish
compound word for chilli paste. Specific queries such as `macaroni` or a brand
and pasta shape give more relevant choices than broad `pasta` searches.
