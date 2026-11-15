#!/usr/bin/env python3
"""Compare lactose-free milk offers, calculate baskets and check a demo spend limit.

Python 3.10+, standard library only. No orders are placed.
Example:
  python milk_compare.py --date 2026-11-16 --litres 1000 --approval-limit 1200
  python milk_compare.py --offline

Keep valio_aimo_junction26_product_data.json beside this script, or use
--catalog PATH. Set AIMO_API_KEY to the supplied mock backend API key.
The approval threshold applies to product subtotals INCLUDING tax, excluding
delivery charges and deposits. It is a demo policy, not an order authorisation.
The name filter is a conservative demo heuristic, not a food-safety guarantee.
Mentor clarification: stock >=999999 is unknown but orderable; 0.01 lot size
means 1. Mock cut-offs stay fixed and are still checked. HTTP 429 pauses the
client for at least 30 seconds. Saved proposals are the challenge deliverable;
no order submission or production webshop interaction is needed.
"""

import argparse
import planning_budget
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from fractions import Fraction
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import sqlite3
import uuid
import unicodedata
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://junction26.valioaimo.fi"
CATALOG = "valio_aimo_junction26_product_data.json"
RULE_VERSION = "mentor-2026-11-14"
UNKNOWN_STOCK_THRESHOLD = Decimal("999999")
_API_LOCK = threading.Lock()
_API_NEXT_REQUEST = 0.0
EXCLUDED = re.compile(
    r"chocolate|powder|fermented|curdled|condensed|sweetened|coffee|cafe|"
    r"bread|butter|pudding|sour|shake|cream|protein|oat|coconut|dessert|"
    r"strawberry|vanilla|drink|mix|portion|wafer|donut|vegan|"
    r"free\W+from\W+milk|milk\W+free|no\W+milk"
)


def name_of(product):
    names = product.get("synkkaData", {}).get("names", [])
    for language in ("en", "fi", "sv"):
        for name in names:
            if name.get("language") == language:
                return name.get("value", "")
    return product["id"]


def shortlist(products, limit):
    """Require an explicit claim and an English plain-milk name."""
    matches = []
    for product in products:
        if product.get("deleted"):
            continue
        data = product.get("synkkaData", {})
        english = next((n.get("value", "") for n in data.get("names", [])
                        if n.get("language") == "en"), "")
        text = unicodedata.normalize("NFKD", english.casefold())
        text = "".join(c for c in text if not unicodedata.combining(c))
        claims = {v.get("id") for group in data.get("classifications", [])
                  if group.get("name") == "nutritionalClaim"
                  for v in group.get("values", [])}
        if ("FREE_FROM_LACTOSE" in claims and re.search(r"\bmilk\b", text)
                and not EXCLUDED.search(text)):
            matches.append(product)
    return sorted(matches, key=lambda p: (name_of(p).casefold(), p["id"]))[:limit]


class NoRedirect(HTTPRedirectHandler):
    # Do not forward the API key to a redirected destination.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api_post(endpoint, payload, api_key):
    """Pace calls and share a 429 cooldown within this running process.

    Three attempts maximum. Wait at least 30 seconds after every 429, and
    longer if Retry-After requests it. Retries are safe for these read queries.
    """
    global _API_NEXT_REQUEST
    request = Request(
        BASE_URL + endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"X-API-Key": api_key, "Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": "AimoChallengeDemo/1.0"},
        method="POST",
    )
    with planning_budget.lock(_API_LOCK):
        planning_budget.check("supplier queue")
        for attempt in range(3):
            while _API_NEXT_REQUEST > time.monotonic():
                planning_budget.check("supplier cooldown")
                time.sleep(max(0.0, min(1.0, _API_NEXT_REQUEST - time.monotonic())))
            _API_NEXT_REQUEST = time.monotonic() + 1.0
            try:
                with build_opener(NoRedirect()).open(request, timeout=planning_budget.timeout(30)) as response:
                    result = json.load(response, parse_float=Decimal)
                break
            except HTTPError as exc:
                if exc.code == 429:
                    seconds = retry_delay(exc.headers.get("Retry-After") if exc.headers else None)
                    _API_NEXT_REQUEST = time.monotonic() + seconds
                    exc.close()
                    if attempt == 2:
                        raise RuntimeError(f"{endpoint}: still rate limited after 3 attempts. "
                                           f"Wait at least {seconds:.0f} seconds before rerunning.") from None
                    print(f"{endpoint}: HTTP 429; pausing {seconds:.0f} seconds before retry "
                          f"{attempt + 2}/3.", file=sys.stderr, flush=True)
                    continue
                advice = {401: "Check your API key.", 403: "Check API access.",
                          422: "Check the customer, date and product codes."}.get(exc.code, "")
                code = exc.code
                exc.close()
                raise RuntimeError(f"{endpoint}: HTTP {code}. {advice}") from None
            except (URLError, TimeoutError, OSError):
                raise RuntimeError(f"{endpoint}: connection failed or timed out.") from None
            except (ValueError, InvalidOperation):
                raise RuntimeError(f"{endpoint}: response was not valid JSON.") from None
    if not isinstance(result, dict) or not isinstance(result.get("products"), list):
        raise RuntimeError(f"{endpoint}: unexpected response structure.")
    return result


def retry_delay(header):
    """Support Retry-After seconds or an HTTP date; never less than 30 s."""
    seconds = decimal_value(header)
    if seconds is not None:
        return max(30.0, float(seconds))
    try:
        when = parsedate_to_datetime(header)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(30.0, (when - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return 30.0


def decimal_value(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def stamp(value):
    """Only compare timestamps with explicit timezone information."""
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def availability_text(item, requested_date, sales_unit, server_time=None):
    if not item:
        return "Unknown: missing response"
    if item.get("salesBlock"):
        return "Blocked"
    lines = item.get("scheduleLines", [])
    if not lines:
        return "Unavailable"
    line = lines[0]  # Supplied API contract specifies at most one line.
    if line.get("salesBlock"):
        return "Blocked"
    if line.get("salesUnit") != sales_unit:
        return "Unknown: sales-unit mismatch"
    cutoff = stamp(item.get("closingTime"))
    now = stamp(server_time) or datetime.now(timezone.utc)
    if cutoff and cutoff < now:
        return "Cut-off passed; recheck"
    try:
        delivery = date.fromisoformat(line["availableDate"][:10])
    except (KeyError, TypeError, ValueError):
        return "Unknown delivery date"
    timing = f"late: {delivery}" if delivery > requested_date else f"by {delivery}"
    quantity = decimal_value(line.get("availableAmount"))
    if quantity is not None and quantity >= UNKNOWN_STOCK_THRESHOLD:
        return f"Orderable; stock quantity unknown; {timing}"
    if quantity is None:
        return f"Quantity unknown; {timing}"
    if quantity <= 0:
        return "Unavailable"
    return f"{quantity:g} {sales_unit}; {timing}"


def comparison_rows(products, prices, availability, requested_date):
    price_map = {p["productId"]: p for p in prices.get("products", [])}
    availability_map = {p["productId"]: p for p in availability.get("products", [])}
    rows = []
    for product in products:
        pid, unit = product["id"], product["salesUnit"]
        price = price_map.get(pid)
        sales_price, per_litre, sort_price = "Unknown", "Unknown", None
        if price and price.get("error") is False:
            catalog = price.get("catalogPrice") or {}
            currency = catalog.get("currency") or prices.get("currency", "?")
            amount = decimal_value(catalog.get("value"))
            basis = decimal_value(price.get("quantity"))
            if amount is not None and basis is not None and basis > 0:
                sales_price = f"{amount / basis:.2f} {currency}/{unit}"
            comparison = price.get("comparisonPrice") or {}
            amount = decimal_value(comparison.get("value"))
            if price.get("comparisonUnit") == "L" and amount is not None:
                sort_price = amount
                per_litre = f"{amount:.3f} {comparison.get('currency', currency)}/L"
        elif price:
            sales_price = "Price unavailable"
        rows.append((sort_price, [pid, name_of(product), sales_price, per_litre,
                    availability_text(availability_map.get(pid), requested_date,
                                      unit, availability.get("timeNow"))]))
    # This is a price comparison, not a recommendation or stock reservation.
    rows.sort(key=lambda r: (r[0] is None, r[0] or Decimal(0), r[1][0]))
    return [r[1] for r in rows]


def print_table(headers, rows):
    def clean(value):
        return " ".join(str(value).split())
    rows = [[clean(v) for v in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows))
              for i, h in enumerate(headers)]
    def render(row):
        return " | ".join(v.ljust(w) for v, w in zip(row, widths))
    print(render(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(render(row))


def positive_decimal(text):
    value = decimal_value(text)
    if value is None or value <= 0:
        raise argparse.ArgumentTypeError("Enter a positive finite number.")
    return value


def litres_per_sales_unit(product, overrides):
    """Use explicit litre volume at each level and the catalogue unit hierarchy.

    Never infer volume from weight, product name or a rounded comparison price.
    ST is the each unit for this demo; other base-unit meanings need confirmation.
    """
    if product["id"] in overrides:
        return overrides[product["id"]], "user-supplied conversion"
    if product.get("baseUnit") != "ST":
        return None, "base-unit meaning needs confirmation"
    conversions = product.get("synkkaData", {}).get("unitConversions", [])
    volumes = set()
    for level in conversions:
        if level.get("synkkaPackagingType") != "BASE_UNIT_OR_EACH":
            continue
        volume = level.get("volume") or {}
        amount = decimal_value(volume.get("value"))
        factor = {"LTR": Decimal(1), "MLT": Decimal("0.001")}.get(volume.get("unit"))
        if amount is not None and amount > 0 and factor is not None:
            volumes.add(amount * factor)
    multipliers = {decimal_value(u.get("sizeInBaseUnits"))
                   for u in product.get("units", [])
                   if u.get("unitId") == product.get("salesUnit")}
    if len(volumes) == 1 and len(multipliers) == 1:
        multiplier = multipliers.pop()
        if multiplier is not None and multiplier > 0:
            return volumes.pop() * multiplier, "catalogue volume and unit hierarchy"
    return None, "no unambiguous litre conversion in catalogue"


def quantity_per_sales_unit(product, unit, overrides):
    """Exact structured conversions only; do not infer mass from volume."""
    if unit == "L":
        return litres_per_sales_unit(product, overrides)
    if unit == "SALES_UNIT":
        return Decimal(1), "requested in catalogue sales units"
    if unit == "PIECE":
        # ST is a catalogue packaging unit, not necessarily one egg/onion.
        # Do not turn a count of bags/cartons into an ingredient piece count.
        return None, "ingredient piece count is not verified; supply an explicit total in KG or L"
    if unit != "KG":
        return None, "unsupported requested unit"
    if product.get("synkkaData", {}).get("variableUnit"):
        return None, "variable-weight product requires a verified weight/price basis"
    # BASE_UNIT_OR_EACH measurements describe the base packaging level.
    # Require an unambiguous hierarchy and explicit net weight.
    multipliers = {decimal_value(u.get("sizeInBaseUnits")) for u in product.get("units", [])
                   if u.get("unitId") == product.get("salesUnit")}
    weights = set()
    for level in product.get("synkkaData", {}).get("unitConversions", []):
        if level.get("synkkaPackagingType") != "BASE_UNIT_OR_EACH":
            continue
        measure = level.get("netWeight") or {}
        amount = decimal_value(measure.get("value"))
        factor = {"KGM": Decimal(1), "GRM": Decimal("0.001")}.get(measure.get("unit"))
        if amount is not None and amount > 0 and factor is not None:
            weights.add(amount * factor)
    if len(weights) == 1 and len(multipliers) == 1:
        multiplier = multipliers.pop()
        if multiplier is not None and multiplier > 0:
            return weights.pop() * multiplier, "catalogue net weight and unit hierarchy"
    # Some records contain only CASE measurements. A CASE net weight is
    # already for the whole case: never multiply it again by the pack count.
    # Require the labelled multipack count to match the sales-unit GTIN's
    # hierarchy multiplier. No weight is inferred from the product name.
    if not weights:
        count = re.match(r"^\s*(\d+)\s*[x×]\s*", name_of(product), re.IGNORECASE)
        gtin = product.get("salesUnitGtin")
        matches = [u for u in product.get("units", []) if gtin and u.get("gtin") == gtin
                   and u.get("unitId") == product.get("salesUnit")]
        if count and len(matches) == 1 and int(count.group(1)) > 1:
            multiplier = decimal_value(matches[0].get("sizeInBaseUnits"))
            if multiplier == Decimal(count.group(1)):
                cases = set()
                for level in product.get("synkkaData", {}).get("unitConversions", []):
                    if level.get("synkkaPackagingType") != "CASE":
                        continue
                    weight = level.get("netWeight") or {}
                    amount = decimal_value(weight.get("value"))
                    factor = {"KGM": Decimal(1), "GRM": Decimal("0.001")}.get(weight.get("unit"))
                    if amount is not None and amount > 0 and factor is not None:
                        cases.add(amount * factor)
                if len(cases) == 1:
                    return cases.pop(), "catalogue CASE net weight; multipack count matches sales-unit GTIN hierarchy"
    return None, "no unambiguous kilogram conversion in catalogue"


def basket_option(product, price, stock, requested_date, now, litres, limit, overrides, *, unit="L"):
    """Evaluate each single-SKU alternative; never commits an order."""
    result = {"sku": product["id"], "name": name_of(product),
              "sales_unit": product["salesUnit"], "requested_litres": litres if unit == "L" else None,
              "requested_quantity": litres, "requested_unit": unit, "provided_quantity": None,
              "quantity": None, "litres": None, "net": None, "gross": None,
              "spend": "UNKNOWN", "readiness": "NEEDS REVIEW", "reasons": [],
              "warnings": [], "stock_status": "UNKNOWN", "rule_version": RULE_VERSION}
    reasons = result["reasons"]
    volume, evidence = quantity_per_sales_unit(product, unit, overrides)
    result["conversion_source"] = evidence
    result["litres_per_sales_unit"] = volume if unit == "L" else None
    result["quantity_per_sales_unit"] = volume
    if volume is None:
        reasons.append(evidence)
    else:
        lot = decimal_value(product.get("allowedLotSize"))
        if lot == Decimal("0.01"):
            lot = Decimal(1)  # Mentor: 0.01 crates is a technical artefact.
        if lot is None or lot <= 0:
            reasons.append("invalid ordering increment")
        else:
            # Whole sale packs AND an exact multiple of allowedLotSize.
            # For 0.01 use step 1; for 2.5 use step 5; for 0.3 use step 3.
            step = Decimal(Fraction(lot).numerator)
            quantity = (litres / volume / step).to_integral_value(rounding=ROUND_CEILING) * step
            result.update(quantity=quantity, litres=quantity * volume if unit == "L" else None,
                          provided_quantity=quantity * volume)
    if not price or price.get("error") is not False:
        reasons.append("price unavailable")
    else:
        catalog = price.get("catalogPrice") or {}
        basis = decimal_value(price.get("quantity"))
        net = decimal_value(catalog.get("value"))
        gross = decimal_value(catalog.get("valueWithTax"))
        if catalog.get("currency") != "EUR":
            reasons.append("price currency not confirmed as EUR")
        elif basis is None or basis <= 0 or net is None or gross is None or net < 0 or gross < net:
            reasons.append("missing or inconsistent price/tax values")
        elif result["quantity"] is not None:
            quantity = result["quantity"]
            result["net"] = (quantity * net / basis).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            result["gross"] = (quantity * gross / basis).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            result["spend"] = "APPROVAL REQUIRED" if result["gross"] > limit else "WITHIN LIMIT"
        try:
            start = date.fromisoformat(catalog["validFrom"][:10])
            end = date.fromisoformat(catalog["validTo"][:10])
            if not start <= requested_date <= end:
                reasons.append("price not valid on delivery date")
        except (KeyError, TypeError, ValueError):
            reasons.append("price validity unknown")
    blocked = False
    if not stock:
        reasons.append("availability response missing")
    elif stock.get("salesBlock"):
        reasons.append("sales blocked")
        blocked = True
    else:
        lines = stock.get("scheduleLines", [])
        if not lines:
            reasons.append("unavailable")
            blocked = True
        else:
            line = lines[0]
            if line.get("salesBlock"):
                reasons.append("schedule-line sales blocked")
                blocked = True
            if line.get("salesUnit") != product["salesUnit"]:
                reasons.append("availability sales-unit mismatch")
            try:
                delivery = date.fromisoformat(line["availableDate"][:10])
                if delivery > requested_date:
                    reasons.append("delivery misses requested date")
                    blocked = True
            except (KeyError, TypeError, ValueError):
                reasons.append("delivery date unknown")
            cutoff = stamp(stock.get("closingTime"))
            if cutoff is None:
                reasons.append("order cut-off missing or timezone unknown")
            elif cutoff < now:
                reasons.append("ordering cut-off passed")
                blocked = True
            amount = decimal_value(line.get("availableAmount"))
            if amount is None:
                reasons.append("stock quantity unknown")
            elif amount >= UNKNOWN_STOCK_THRESHOLD:
                result["stock_status"] = "UNKNOWN_ORDERABLE"
                result["warnings"].append("Stock quantity unknown; ordering any quantity is permitted by mock rules, not guaranteed stock.")
            elif amount <= 0 or (result["quantity"] is not None and amount < result["quantity"]):
                reasons.append("insufficient stock for full basket")
                result["stock_status"] = "INSUFFICIENT"
                blocked = True
            else:
                result["stock_status"] = "KNOWN"
    if blocked:
        result["readiness"] = "BLOCKED"
    elif not reasons:
        result["readiness"] = ("CHECKS PASSED (STOCK UNKNOWN)"
                               if result["stock_status"] == "UNKNOWN_ORDERABLE" else "CHECKS PASSED")
    return result


def show_baskets(products, prices, availability, args, overrides):
    price_map = {p["productId"]: p for p in prices.get("products", [])}
    stock_map = {p["productId"]: p for p in availability.get("products", [])}
    now = stamp(availability.get("timeNow")) or datetime.now(timezone.utc)
    options = [basket_option(p, price_map.get(p["id"]), stock_map.get(p["id"]),
                             args.date, now, args.litres, args.approval_limit, overrides)
               for p in products]
    options.sort(key=lambda o: (o["gross"] is None, o["gross"] or Decimal(0)))
    fmt = lambda v: "Unknown" if v is None else f"{v:f}"
    print(f"\nSINGLE-PRODUCT BASKET ALTERNATIVES: {args.litres:g} litres")
    print(f"Demo spend policy: EUR {args.approval_limit:.2f}, product subtotal INCLUDING tax.")
    print("Whole sales units only. Delivery fees/deposits are not included; no final order authority.\n")
    print_table(["SKU", "Order quantity", "Litres", "EUR excl. tax", "EUR incl. tax", "Spend policy", "Readiness"],
                [[o["sku"], f"{fmt(o['quantity'])} {o['sales_unit']}", fmt(o["litres"]),
                  fmt(o["net"]), fmt(o["gross"]), o["spend"], o["readiness"]] for o in options])
    for o in options:
        print(f"\n{o['sku']}: {o['name']}")
        print(f"  Conversion: {fmt(o['litres_per_sales_unit'])} L/{o['sales_unit']} ({o['conversion_source']}).")
        print("  " + ("; ".join(o["reasons"]) if o["reasons"] else "Listed availability and pricing checks passed."))
        for warning in o["warnings"]:
            print(f"  Notice: {warning}")
    eligible = [o for o in options if o["readiness"].startswith("CHECKS PASSED") and o["gross"] is not None]
    if eligible:
        best = min(eligible, key=lambda o: o["gross"])
        print(f"\nLowest product subtotal among options passing checks: {best['sku']}, "
              f"EUR {best['gross']:.2f} incl. tax. Spend decision: {best['spend']}.")
    else:
        print("\nNo option currently passes all checks. Resolve the reasons above before proceeding.")
    print("Stock values >=999999 permit ordering under mock rules; actual stock remains unknown.")
    print("Sales blocks, empty schedules, missed delivery dates and cut-offs still block readiness.")
    print("Mock dates stay fixed over the weekend; expired cut-offs are not silently ignored.")
    print("Challenge deliverable: an order proposal for human approval. No order API or webshop submission is used.")
    return options


def proposal_db(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE IF NOT EXISTS proposals (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
        snapshot TEXT NOT NULL, digest TEXT NOT NULL, spending_status TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS proposal_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT NOT NULL,
        at TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL,
        snapshot_digest TEXT NOT NULL)""")
    connection.commit()
    return connection


def utc_now():
    return datetime.now(timezone.utc)


def snapshot_digest(snapshot):
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()


def load_proposal(connection, pid):
    row = connection.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise RuntimeError(f"Proposal {pid} not found. Use --list-proposals.")
    if snapshot_digest(row["snapshot"]) != row["digest"]:
        raise RuntimeError("Proposal snapshot changed: approval refused.")
    return row, json.loads(row["snapshot"])


def save_proposal(connection, option, product, prices, availability, args):
    if option["quantity"] is None or option["gross"] is None or option["spend"] == "UNKNOWN":
        raise RuntimeError("Cannot save this SKU: quantity, conversion or price is unresolved.")
    created = utc_now()
    # Local demo validity window; this is not a supplier price lock or reservation.
    expiry = created + timedelta(minutes=30)
    payload = {"schema_version": 2, "rule_version": RULE_VERSION, "customer": args.customer,
               "delivery_date": args.date.isoformat(),
               "policy": {"limit_eur_including_tax": str(args.approval_limit),
                          **getattr(args, "policy_metadata", {}),
                          "basis": "product subtotal only; delivery and deposits excluded"},
               "basket": option, "product": product,
               "price_snapshot": next(p for p in prices["products"] if p["productId"] == option["sku"]),
               "stock_snapshot": next((p for p in availability["products"] if p["productId"] == option["sku"]), None),
               "availability_time": availability.get("timeNow"),
               "created_at": created.isoformat(), "expires_at": expiry.isoformat()}
    snapshot = json.dumps(payload, default=str, sort_keys=True, ensure_ascii=False)
    digest = snapshot_digest(snapshot)
    pid = "P-" + uuid.uuid4().hex[:12]
    status = "PENDING" if option["spend"] == "APPROVAL REQUIRED" else "AUTO_AUTHORISED"
    with connection:
        connection.execute("INSERT INTO proposals VALUES (?,?,?,?,?,?)",
                           (pid, created.isoformat(), expiry.isoformat(), snapshot, digest, status))
        connection.execute("INSERT INTO proposal_events (proposal_id,at,action,actor,note,snapshot_digest) VALUES (?,?,?,?,?,?)",
                           (pid, created.isoformat(), "CREATED", "purchasing-script",
                            "Saved exact basket and evidence; no order placed.", digest))
        if status == "AUTO_AUTHORISED":
            connection.execute("INSERT INTO proposal_events (proposal_id,at,action,actor,note,snapshot_digest) VALUES (?,?,?,?,?,?)",
                               (pid, created.isoformat(), "AUTO_AUTHORISED", "purchasing-gateway",
                                "Product subtotal including tax is within configured per-proposal authority; no human sign-off required. No order submitted.", digest))
    return pid


def display_proposal(connection, pid):
    row, snapshot = load_proposal(connection, pid)
    basket = snapshot["basket"]
    expired = utc_now() >= datetime.fromisoformat(row["expires_at"])
    print(f"\nPROPOSAL {pid} | customer {snapshot['customer']} | delivery {snapshot['delivery_date']}")
    print(f"{basket['name']} ({basket['sku']})")
    qty = decimal_value(basket['quantity'])
    quantity_text = f"{qty:f}" if qty is not None else "Unknown"
    print(f"Basket: {quantity_text} {basket['sales_unit']} = {basket['litres']} litres")
    print(f"Product subtotal: EUR {basket['net']} excl. tax / EUR {basket['gross']} incl. tax")
    print(f"Spend limit: EUR {snapshot['policy']['limit_eur_including_tax']} incl. tax")
    print(f"Spending decision: {row['spending_status']}")
    print(f"Saved stock/delivery assessment: {basket['readiness']}")
    for reason in basket["reasons"]:
        print(f"  - {reason}")
    for warning in basket.get("warnings", []):
        print(f"  Notice: {warning}")
    if snapshot.get("rule_version") != RULE_VERSION:
        print("Legacy proposal: predates mentor clarification. Create a fresh proposal to apply current rules.")
    print(f"Validity: {'EXPIRED' if expired else 'within local 30-minute review window'}; expires {row['expires_at']}")
    print(f"Basket fingerprint: {row['digest'][:16]}")
    print("Challenge output: saved order proposal for human approval; no submission is required or attempted.")
    print("This is not a stock reservation or delivery guarantee. Delivery fees/deposits are excluded.")
    print("Local demo only: reviewer names are self-declared; no authenticated human identity.")
    print("History:")
    for event in connection.execute("SELECT * FROM proposal_events WHERE proposal_id=? ORDER BY sequence", (pid,)):
        print(f"  {event['at']} | {event['action']} | {event['actor']} | {event['note']}")
    return row, snapshot


def decide_proposal(connection, pid, decision, actor, note, expected_digest):
    if decision not in ("APPROVED", "REJECTED"):
        raise RuntimeError("Invalid decision.")
    if not actor.strip():
        raise RuntimeError("A reviewer name is required.")
    if decision == "REJECTED" and not note.strip():
        raise RuntimeError("A rejection reason is required.")
    try:
        connection.execute("BEGIN IMMEDIATE")
        row, snapshot = load_proposal(connection, pid)
        if row["digest"] != expected_digest:
            raise RuntimeError("Basket changed since review. Open a fresh proposal.")
        if row["spending_status"] != "PENDING":
            raise RuntimeError(f"Proposal spending status is already {row['spending_status']}.")
        if utc_now() >= datetime.fromisoformat(row["expires_at"]):
            raise RuntimeError("Proposal expired. Fetch fresh offers and save a new proposal.")
        if date.fromisoformat(snapshot["delivery_date"]) < utc_now().date():
            raise RuntimeError("Delivery date is in the past. Create a new proposal.")
        connection.execute("UPDATE proposals SET spending_status=? WHERE id=?", (decision, pid))
        connection.execute("INSERT INTO proposal_events (proposal_id,at,action,actor,note,snapshot_digest) VALUES (?,?,?,?,?,?)",
                           (pid, utc_now().isoformat(), decision, actor.strip(),
                            note.strip() or "Spending approved for this exact saved basket only.", row["digest"]))
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def proposal_command(args):
    """These commands use local records only, with no API key or catalogue needed."""
    with proposal_db(args.db) as connection:
        if args.list_proposals:
            records = connection.execute("SELECT id FROM proposals ORDER BY created_at DESC").fetchall()
            if not records:
                print("No saved proposals. Run a comparison with --save-proposal SKU.")
                return
            rows = []
            for record in records:
                row, saved = load_proposal(connection, record["id"])
                basket = saved["basket"]
                valid = "EXPIRED" if utc_now() >= datetime.fromisoformat(row["expires_at"]) else "REVIEW WINDOW"
                rows.append([row["id"], basket["sku"], str(basket["gross"]), row["spending_status"], basket["readiness"], valid])
            print_table(["Proposal", "SKU", "EUR incl. tax", "Spending", "Saved readiness", "Validity"], rows)
            return
        pid = args.show_proposal or args.approve or args.reject
        row, _ = display_proposal(connection, pid)
        if args.show_proposal:
            return
        if not args.reviewer or not args.reviewer.strip():
            raise RuntimeError("Provide --reviewer YOUR_NAME (local demo identity only).")
        if args.reject and not args.reason.strip():
            raise RuntimeError("Provide --reason with the rejection explanation.")
        verb = "APPROVE" if args.approve else "REJECT"
        print("\nThis records a spending decision only; it does not clear readiness issues or place an order.")
        response = input(f"Type {verb} {pid} to confirm, or press Enter to cancel: ").strip()
        if response != f"{verb} {pid}":
            print("Cancelled; no decision recorded.")
            return
        decide_proposal(connection, pid, "APPROVED" if args.approve else "REJECTED",
                        args.reviewer, args.reason, row["digest"])
        display_proposal(connection, pid)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog", type=Path,
                        default=Path(__file__).resolve().with_name(CATALOG))
    parser.add_argument("--customer", default="123", help="Synthetic customer identifier")
    parser.add_argument("--date", type=date.fromisoformat,
                        default=date.today() + timedelta(days=3),
                        help="Delivery date YYYY-MM-DD; default: today + 3 days")
    parser.add_argument("--limit", type=int, default=5, help="Shortlist size, 1-20")
    parser.add_argument("--offline", action="store_true", help="Search only; no API calls")
    parser.add_argument("--litres", type=positive_decimal, default=Decimal("1000"))
    parser.add_argument("--approval-limit", type=positive_decimal, default=Decimal("1200"),
                        help="Demo limit in EUR on product subtotal INCLUDING tax")
    parser.add_argument("--litres-per-sales-unit", action="append", default=[], metavar="SKU=LITRES",
                        help="Explicit, verified volume mapping if catalogue data is missing; repeatable")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--save-proposal", metavar="SKU", help="Save one calculated basket for review")
    actions.add_argument("--list-proposals", action="store_true")
    actions.add_argument("--show-proposal", metavar="ID")
    actions.add_argument("--approve", metavar="ID", help="Record local demo spending approval")
    actions.add_argument("--reject", metavar="ID", help="Record local demo spending rejection")
    parser.add_argument("--reviewer", help="Self-declared demo reviewer name")
    parser.add_argument("--reason", default="", help="Decision note; required for rejection")
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().with_name("purchase_proposals.sqlite3"))
    args = parser.parse_args()
    if args.list_proposals or args.show_proposal or args.approve or args.reject:
        try:
            proposal_command(args)
            return 0
        except (OSError, ValueError, RuntimeError, sqlite3.Error, EOFError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    if args.offline and args.save_proposal:
        parser.error("Cannot save a priced proposal in offline search mode.")
    if not 1 <= args.limit <= 20:
        parser.error("--limit must be between 1 and 20")
    overrides = {}
    for mapping in args.litres_per_sales_unit:
        try:
            sku, raw = mapping.split("=", 1)
            if not sku.strip():
                raise ValueError
            overrides[sku.strip()] = positive_decimal(raw)
        except (ValueError, argparse.ArgumentTypeError):
            parser.error("--litres-per-sales-unit must be SKU=POSITIVE_NUMBER")
    try:
        with args.catalog.open(encoding="utf-8") as source:
            products = json.load(source)
        if not isinstance(products, list):
            raise ValueError("Catalogue must contain a JSON array.")
        chosen = shortlist(products, args.limit)
        if not chosen:
            print("No plain lactose-free milk candidates matched the demo filter.")
            return 0
        print(f"Shortlisted {len(chosen)} of {len(products):,} products. "
              f"Delivery requested: {args.date}")
        print("Conservative name filter + explicit FREE_FROM_LACTOSE claim.\n")
        if args.offline:
            print_table(["SKU", "Product", "Sales unit", "Order increment"],
                        [[p["id"], name_of(p), p["salesUnit"],
                          "1 (raw 0.01)" if decimal_value(p["allowedLotSize"]) == Decimal("0.01") else str(p["allowedLotSize"])]
                         for p in chosen])
            print("\nOffline mode: no prices or availability were requested.")
            return 0
        key = ""
        key = os.environ.get("AIMO_API_KEY", key).strip()
        if not key:
            raise RuntimeError("An API key is required.")

        payload = {
            "customer": args.customer,
            "requestedDate": args.date.isoformat(),
            "products": [p["id"] for p in chosen],
        }
        prices = api_post("/api/price", payload, key)
        availability = api_post("/api/availability", payload, key)
        print_table(["SKU", "Product", "Price excl. tax", "Comparison excl. tax", "Availability"],
                    comparison_rows(chosen, prices, availability, args.date))
        print("\nSorted by reported price per litre; unavailable products remain visible.")
        print("Availability quantities are SALES UNITS, not litres. No stock is reserved.")
        print("Prices exclude tax and do not establish a delivered basket total.")
        options = show_baskets(chosen, prices, availability, args, overrides)
        if args.save_proposal:
            option = next((o for o in options if o["sku"] == args.save_proposal), None)
            if option is None:
                raise RuntimeError("Requested proposal SKU is not in this shortlist.")
            product = next(p for p in chosen if p["id"] == args.save_proposal)
            with proposal_db(args.db) as connection:
                pid = save_proposal(connection, option, product, prices, availability, args)
                display_proposal(connection, pid)
            print(f"\nReview later: python milk_compare.py --show-proposal {pid}")
            print(f"Approve spending: python milk_compare.py --approve {pid} --reviewer YOUR_NAME")
            print(f'Reject spending: python milk_compare.py --reject {pid} --reviewer YOUR_NAME --reason "Reason"')
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
