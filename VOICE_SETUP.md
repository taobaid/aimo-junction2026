# Voice meal requests (v0.7)

The supplied voice orb is now part of the existing dashboard: sign in, then
choose **Speak your request**. The existing server also hosts `/vapi-webhook`;
do NOT start the old separate bridge process. `frontend.html` has been adapted
into the voice dialog, `static/voice.css` and `static/voice.js`.

Say a dish, portions, dietary needs and delivery date. The assistant starts a
background meal job; it can take several minutes. The basket appears in the
existing meal screen with the same substitution/omission choices and Yes/No.
Voice never receives the reviewer token and cannot approve a basket. Even if a
voice tool asks for auto-commit, the gateway creates a review-only plan. The
reviewer signs in normally to confirm the exact basket. All receipts are mock.

## 1. Local settings

In the same PowerShell terminal you use to start the gateway, keep your normal
AIMO and Claude settings and add a new random webhook secret:

```powershell
$env:VAPI_WEBHOOK_SECRET = (python -c "import secrets; print(secrets.token_urlsafe(32))")
# Optional: permit the existing documented kitchen estimates for voice plans.
$env:AIMO_RECIPE_MEASUREMENTS = "kitchen"
python aimo_api.py
```

The public Vapi key and assistant ID from your supplied frontend are defaults.
Override them with `VAPI_PUBLIC_KEY` and `VAPI_ASSISTANT_ID` if necessary.
Only Vapi PUBLIC keys belong in browser configuration. Aimo, Claude, gateway
and webhook secrets remain on the server. No private Vapi API key is needed
by this bridge. The assistant still needs its normal Vapi model/voice setup.

## 2. Connect the assistant in Vapi

The Vapi cloud must reach your server over HTTPS. Configure your existing
HTTPS deployment/tunnel to forward `/vapi-webhook` to localhost port 8000.
Keep the gateway bound to localhost behind that forwarding; you do not need to
expose additional routes for the webhook. This ZIP does not create a tunnel.
If your gateway is remote, open its HTTPS dashboard so the microphone works;
localhost is also a browser secure context. A local-only `127.0.0.1` URL cannot
be called from Vapi's cloud.

In Vapi, create/attach the three **Function tools** described by
`vapi_tools.json` (use each `function.parameters` object in its Parameters
editor). For each tool configure:

- Server URL: your HTTPS URL ending in `/vapi-webhook`.
- Request header `X-Vapi-Secret`: the exact value of `VAPI_WEBHOOK_SECRET`.
  Use Vapi's server authentication/custom-header configuration; never place
  this secret in model-visible function arguments or the public browser key.
- **Async off.** These functions return an immediate job ID/status; the actual
  meal research runs in the gateway background. Vapi's async mode discards the
  eventual webhook response, so it is not needed here.
- Keep or enable client messages `transcript`, `tool-calls`, `speech-update`.

The JSON contains tool definitions, not account credentials or a configured
server URL. It is a configuration template; create each tool and attach its
saved tool ID to the supplied assistant in your Vapi dashboard. This cannot be
automatically configured from a public key alone.

Add these instructions to your assistant's system prompt:

> Collect the dish, number of portions and confirmed delivery date. Never invent
> a delivery date; convert relative dates only after confirming the exact date.
> Collect dietary and recipe preferences. Call create_recipe_plan once per new
> request; save its job ID. Tell the caller the basket is being prepared and may
> take several minutes. Do not repeatedly start the same job. If asked for
> progress, use get_recipe_plan_status with the saved job ID (not a plan ID).
> Only report server-returned facts, totals, issues and proposed changes. A READY
> job can still contain a blocked basket. Do not claim food is ordered, stock is
> guaranteed or a voice Yes is an authenticated approval. Tell the buyer to
> review the basket on screen and use Yes/No there. search_products is catalogue
> search only; it does not verify price or stock. Never request private keys.

## 3. Try it

Sign in with your reviewer token, choose Speak your request, then Start voice
request. Microphone audio goes to Vapi and its configured voice/model providers.
Use synthetic challenge requests. Try “Spaghetti bolognese for 200 people,
delivered on November 17, 2026.” The date must still be orderable under mock
cut-offs. End call stops audio; a started basket continues and appears on screen.
Closing the voice dialog stops live tracking; completed baskets remain under
Recent meal plans. A gateway restart interrupts unfinished background jobs;
start a new request rather than assuming they completed. Tracking ends after
20 minutes. Do not run multiple calls in the same browser tab.

## Troubleshooting

- Voice setup needed: set the webhook secret in the server terminal and restart.
- Webhook 401: Vapi's X-Vapi-Secret header and the server value differ.
- No tools/jobs: attach the tools to the right assistant, use a reachable HTTPS
  URL, and inspect Vapi's webhook log. Its Test panel may send just arguments;
  this handler expects the real `message.type=tool-calls` envelope with call ID.
- No microphone: allow it in your browser and use localhost or HTTPS.
- Planning FAILED: check your Aimo/Claude server configuration and credits;
  no raw private upstream errors are spoken or returned through the bridge.
- Product lookup is static only. The recipe workflow obtains prices and stock
  through the existing gateway before showing a proposal.

## Verification and scope

108 offline tests cover the gateway, recipe planner and voice bridge, including
JSON-string arguments, duplicate delivery, unknown tools, failed jobs, webhook
authentication, call-bound status and prevention of voice auto-commit. Browser
UI testing uses a local Vapi/model/supplier fixture, not a paid live call.
Live audio, your Vapi account/tool configuration and public HTTPS routing need
verification in your environment. No second API key or Python dependency was added.

References: https://docs.vapi.ai/tools/custom-tools and
https://docs.vapi.ai/quickstart/web (checked 2026-11-14).

## v0.8.2 date grounding
The browser refreshes /voice/config before each start and passes a date-grounded
firstMessage plus variableValues.current_date/current_year. These use the same
UTC server clock as delivery validation. The saved model, tools and webhook URL
are unchanged. You may add this to the saved system prompt for stronger grounding:

```text
The ordering date is {{current_date}} and the current year is {{current_year}}.
Never use a past delivery date. Confirm ambiguous dates including their year.
If create_recipe_plan returns an error, planning has not started. Ask for the
correct date and retry only after confirmation. Say preparation has started
only when the result contains status PLANNING and a job ID.
```

Past dates now fail synchronously before queueing. The agent must not silently
change 2024 to 2026. A corrected request in the same call can create a normal
review-only basket. No live audio/model test was run for this update.


## v0.13 faster planning

The backend now defaults voice recipe requests to `planning_mode="quick"`, which
uses an AI-planned metric recipe draft without web research. No tool re-upload is
needed for that default. The updated `vapi_tools.json` also exposes an optional
`planning_mode` value of `published` when the buyer asks for a published recipe.
A supplied recipe URL or complete recipe text always takes priority.

Add to the assistant prompt: “Quick planning proposes an AI recipe draft for
on-screen review. Do not call it a published or verified recipe. Only report the
server-returned recipe provenance, basket status and issues. Never claim that
PLANNING or READY means food has been ordered.”
