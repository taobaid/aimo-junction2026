# General partial purchases — v0.15

## User flow

1. Open any blocked recipe that contains some checked products.
2. Click **Continue with available items**.
3. Review the excluded ingredient names/reasons, remaining products and new total.
4. Choose **Yes, confirm partial basket** or Decline.

This works for lasagna, curry, tacos or any other saved dish. It does not depend
on a bolognese name or a seasoning whitelist. Missing meat, cheese, vegetables,
passed cut-offs and unresolved quantities can all be excluded from the PURCHASE.
The program does not assert that the recipe still works without them, that the
kitchen already has them, or that the requested portions can be served.

Excluded ingredients remain visible in the basket history and structured receipt.
They receive NOT_ORDERED_PENDING_APPROVAL, not MATCHED. Their unresolved quantities
remain unresolved. The receipt identifies SELECTED_ITEMS_ONLY and explicitly sets
complete_recipe_basket=false. Exclusions survive a quantity rebuild and cannot
silently become a complete-meal receipt. Both the initial proposal and final
receipt remain separate from any supplier order, which the challenge API lacks.

## Speed and checks

POST /recipe-plans/{id}/partial takes the exact saved fingerprint. It reuses the
recipe, quantities and selected product identities. No paid Claude search,
extraction, matching or alternative recipe calls are made. It only refreshes
supplier prices and availability for retained products, in existing batches.
Final reviewer confirmation revalidates those retained products once more.

The partial basket always needs explicit reviewer approval, even below spending
authority or when the original request selected automatic mode. Agent credentials
may propose it but cannot confirm it. Empty baskets, stale fingerprints and
changed prices/stock/policy still stop commitment. Previously expired plans may
prepare a fresh partial proposal if the retained products pass new checks.

This capability needs actual checked products. If no product can be purchased,
there is no partial order to create. An incomplete source without priced product
lines cannot turn into an invented basket. Use a new quick plan or valid product
request to obtain actual eligible offers.

## Verification

184 offline tests pass. New cases cover the lasagna screenshot's passed-cutoff
beef, unresolved tomatoes/garlic and absent parmesan, six different dish names,
no new Claude calls, just two supplier calls for the small fixture, explicit
reviewer confirmation, receipt scope, excluded-item persistence, fresh stock and
price failures, policy changes, expiry, empty baskets and fingerprint validation.
Browser fixture QA verified the blocked lasagna, revised partial basket and final
partial mock receipt. Live supplier latency was not benchmarked.
