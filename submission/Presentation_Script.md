## Slide 1

Trusted Trade turns a kitchen request into a priced ingredient basket. A buyer can ask for spaghetti bolognese for two hundred people instead of selecting every pack manually. The buyer controls the agent’s authority and reviews the changes that matter.

## Slide 2

Foodservice purchasing involves recipe choice, scaling, product lookup and exceptions. A more convenient search box still leaves those decisions with the buyer. Our prototype handles the ingredient workflow and presents a combined basket, with clear prices, availability and the remaining choices.

## Slide 3

The dashboard, voice assistant and external Python client share a structured API. Claude proposes recipe facts and catalogue matches. Python calculates quantities, prices and tax, enforces recorded requirements and checks delivery. The challenge supplies no order API, so commitment produces a local mock receipt after fresh checks.

## Slide 4

Here is a concrete exception. The agent can keep a bolognese recipe and propose leaving out unavailable wine, rather than restarting research. The buyer sees the flavour trade-off and confirms the changed basket. Essential ingredients cannot disappear silently. Saved plans support targeted substitute searches without repeating the whole recipe lookup.

## Slide 5

This example uses the milk scenario from the challenge. The sample product subtotal is seventeen hundred and seventy euros, above a twelve hundred euro authority. The agent must request spending approval. Eligible purchases within authority can proceed automatically. AI-generated recipe drafts and recipe changes require review. Approval applies to the exact basket and never overrides a validation failure.

## Slide 6

The prototype covers the three required paths: structured product, price and availability lookup, a defined inquiry-to-commitment interaction, and permissions with human approval. The optional recipe and exception flow adds practical value. Each receipt retains evidence and decision history. We expose the interface through OpenAPI so the solution works beyond our dashboard.

## Slide 7

We provide a repeatable laptop demo. After installing Python dependencies, judges can run it without keys or external API calls. It uses fixed sample recipes and synthetic offers through the real approval and receipt routes. Live mode uses the official catalogue and the tester’s own API keys. We never distribute private keys in the source package.

## Slide 8

Our verification includes one hundred and seventy-three offline tests and browser checks. These prove controlled code paths, not arbitrary dish quality or guaranteed live latency. The prototype uses local credentials and creates mock receipts. Production work would add stronger identity, complete delivered costs and supplier order integration. The code package lets judges reproduce the current workflow today.
