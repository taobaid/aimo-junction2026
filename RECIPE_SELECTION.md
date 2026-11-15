## v0.13 quick mode

The dashboard, voice and local diagnostic default to an AI recipe draft for review.
Published-source selection below applies to published mode and exact recipe links.
See FAST_PLANNING.md for the new mode and time-budget behavior.

# Recipe selection v0.8

## Three ways to select a recipe

1. **Dish request** (default): name any dish, portions, delivery date and
   preferences. The model searches published recipes, including regional and
   alternate spellings. It prefers complete ingredient lists and explicit
   serving yields/metric amounts. A good first candidate stops the search.
2. **Exact URL**: expand “Use your own recipe” in the meal form and paste a
   public recipe link. The agent must retrieve and extract that recipe, rather
   than silently picking another one. If it is inaccessible, paste the text.
3. **Your own recipe**: paste the complete ingredient list with the ORIGINAL
   number of servings and quantities. The system scales it to the requested
   portions, looks up products and follows normal basket review. Include all
   components such as sauce/dough/marinade. Pasted text takes priority over a
   supplied URL. It is labelled buyer-provided and always needs review.

No menu or hardcoded dish list is required. Selecting a recipe and sourcing
its basket are separate steps: a valid recipe can still contain unavailable
products or unresolvable quantities. Existing substitutions, cooking-water
and cooking-wine omission rules continue to operate. Mandatory claims/origin,
cut-offs, prices and aggregate stock checks still apply.

## What changed

- Up to THREE search/extract attempts, only when the candidate needs repair.
- Retain the best usable candidate if a later source/extraction fails.
- Rank by completeness, known positive original serving yield, measurable
  quantity coverage and review concerns. Never merge different recipes.
- Carry the user's dish and dietary preferences into extraction as well as
  research; include every required ingredient section and missing sub-recipes.
- Up to 80 ingredients; catalogue matching is performed in batches of eight.
  SKU IDs are still checked against supplied candidates on every batch.
- Authentication, rate-limit and transport/time-out errors do not trigger
  automatic repeated paid lookups. Source/extraction failures can try another
  source within the bounded budget.
- Exact source quantities remain separate from buyer-approved kitchen estimates.
  A cake/loaf count must not be invented into a serving yield. Missing required
  amounts remain explicit; arbitrary ingredient weights are not guessed.
- No source-free generated recipe is presented as a published recipe. User text
  is labelled as such. Recipe facts and dietary interpretation remain AI-extracted,
  not independently certified.

## External agent API

POST /recipe-plans accepts two new optional string fields:

```json
{
  "request": "My vegetable curry",
  "portions": 200,
  "delivery_date": "2026-11-17",
  "preferences": "vegan",
  "recipe_url": "",
  "recipe_text": "Serves 4. [Full ingredient list and exact quantities here]",
  "autonomy": "review",
  "auto_commit": false,
  "measurement_mode": "kitchen"
}
```

The example bracketed text is an instruction placeholder, not a usable recipe.
Recipe text is capped at 20,000 characters. Only public HTTP/HTTPS URLs without
embedded credentials are accepted. URL retrieval remains provider-side; the
Python gateway does not fetch arbitrary recipe URLs itself.

CLI examples (use an actually eligible mock delivery date):

```powershell
python recipe_client.py "Vegetable curry for 200" --portions 200 --date 2026-11-17 --kitchen-estimates
python recipe_client.py "My curry" --portions 200 --date 2026-11-17 --recipe-file my_recipe.txt
python recipe_client.py "My curry" --portions 200 --date 2026-11-17 --recipe-url "https://YOUR_RECIPE_PAGE"
```

Voice automatically uses the improved dish selector. To accept spoken recipe
links/text, update the optional properties in the Vapi create_recipe_plan tool
using vapi_tools.json. Existing required tool parameters are unchanged.
Keep your working VAPI_PUBLIC_KEY, VAPI_ASSISTANT_ID and VAPI_WEBHOOK_SECRET.
If you changed the old defaults directly in code, transfer those identifiers to
server environment settings before replacing files.

## Verification

120 offline tests pass, including the existing price, stock, policy and voice
flows; third-source recovery; failed extraction; retaining the best candidate;
no timeout retries; chosen-URL protection; pasted-recipe approval; large matching
batches and general scaling for salmon soup, dal, curry, lasagne, tofu stir fry,
pancakes, apple crumble and rice pudding. These are synthetic fixtures, not
proof of successful live web searches for each dish. No provider key was available
in this environment and no live supplier/model calls were performed.

Useful live checks on your server: a common metric recipe, a regional dish,
a vegan dish, a baking recipe, an inaccessible URL, and a full pasted recipe.
All required quantities should scale once from the original serving yield.
An unavailable product may lead to a proposed change or a genuine sourcing
blocker; neither should cause invented stock or silent ingredient removal.

“Any recipe” means an open-ended dish/request interface plus support for your
own recipes. It cannot guarantee every website is retrievable, every serving
amount exists or every ingredient can be bought from the mock catalogue.
All order commitments remain mock-only.

## v0.10 consistent recipe reuse
Successful local, UI and voice source recipes share a 24-hour source record in
the same AIMO_DB. Match the dish, portions, preferences and measurement policy.
Prices, stock, approvals and receipts are not cached. Use --fresh in dish_check
or Find a new recipe in the UI to deliberately research again. Exact URLs and
pasted recipes bypass this store. See README.md for the upgrade/test sequence.
