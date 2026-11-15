"""External client: search, compare, propose and commit mock orders; cannot approve."""
import argparse
from datetime import date
import os
import sys
import httpx
from urllib.parse import urlsplit
import json

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--commit-proposal", help="Commit an already approved/auto-authorised proposal ID")
    parser.add_argument("--draft-only", action="store_true", help="Stop at proposal creation even if within authority")
    parser.add_argument("--litres", default="1000")
    parser.add_argument("--query", help="Catalogue product-name query; omit for the lactose-free milk example")
    parser.add_argument("--quantity", help="Requested amount; use with --unit")
    parser.add_argument("--unit", choices=["L", "KG", "SALES_UNIT"], default="L")
    parser.add_argument("--required-claim", action="append", default=[], help="Exact recorded claim code; repeatable")
    parser.add_argument("--origin", help="Required lower-case two-letter country code")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if not args.commit_proposal and not args.date:
        parser.error("Provide --date, or use --commit-proposal with an existing proposal ID.")
    token = os.environ.get("AIMO_AGENT_TOKEN", "").strip()
    if not token:
        sys.exit("Set AIMO_AGENT_TOKEN to the local agent token printed by the server.")
    with httpx.Client(base_url=args.url, headers={"Authorization": f"Bearer {token}"}, timeout=180,
                          trust_env=urlsplit(args.url).hostname not in {"localhost","127.0.0.1","::1"}) as client:
        if args.commit_proposal:
            receipt = client.post("/orders", json={"proposal_id": args.commit_proposal})
            receipt.raise_for_status()
            print("Mock order:", receipt.json()["id"], "|", receipt.json()["status"])
            print("Fresh checks passed. Retrying this proposal returns the same receipt. No supplier order sent.")
            return
        milk = args.query is None
        search = client.get("/products", params={"q": args.query or "", "plain_milk": str(milk).lower(), "limit": 20})
        search.raise_for_status()
        print("Static search returned", len(search.json()["products"]), "candidates (first page).")
        request = {"delivery_date": args.date.isoformat(), "quantity": args.quantity or args.litres,
                   "unit": args.unit, "query": args.query or "", "plain_milk": milk,
                   "required_claims": args.required_claim, "required_origin": args.origin}
        offer = client.post("/offers", json=request)
        offer.raise_for_status()
        offer = offer.json()
        eligible = [o for o in offer["options"] if o["readiness"].startswith("CHECKS PASSED") and o["gross"] is not None]
        if not eligible:
            print("No basket passes checks:")
            for option in offer["options"]:
                print(option["sku"], option["readiness"], "; ".join(option["reasons"]))
            return
        from decimal import Decimal
        chosen = min(eligible, key=lambda o: Decimal(o["gross"]))
        print(f"Selected {chosen['sku']}: lowest eligible product subtotal, EUR {chosen['gross']} including tax.")
        print("Stock status:", chosen["stock_status"])
        proposal = client.post("/proposals", json={"offer_id": offer["id"], "sku": chosen["sku"]})
        proposal.raise_for_status()
        proposal = proposal.json()
        print("Proposal:", proposal["id"])
        print("Spending:", proposal["spending_status"])
        print("Fingerprint:", proposal["fingerprint"])
        if proposal["spending_status"] == "AUTO_AUTHORISED":
            if args.draft_only:
                print("Within authority. Draft-only mode: no mock commitment made.")
            else:
                receipt = client.post("/orders", json={"proposal_id": proposal["id"]})
                receipt.raise_for_status()
                print("Mock order:", receipt.json()["id"], "|", receipt.json()["status"])
                print("No human sign-off required. No supplier order sent.")
        else:
            print("Human approval required. Open the reviewer dashboard using its separate token. No order sent.")
            print("After approval: python agent_client.py --commit-proposal", proposal["id"])

if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        sys.exit(f"Gateway HTTP {exc.response.status_code}: {exc.response.text}")
    except httpx.RequestError as exc:
        sys.exit(f"Could not reach the local gateway: {exc}")
