"""Local purchasing gateway. Run: python aimo_api.py

One configured buyer, a separate reviewer credential, and no order submission.
"""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hmac
import json
import os
import re
from pathlib import Path
import secrets
import sqlite3
import threading
from types import SimpleNamespace
from typing import Annotated, Literal
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
import uvicorn

import aimo_core as core

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Trusted Trade Agents", version="0.15.0",
              description="Local demo: static search → fixed-price offers → order proposals → reviewer approval. "
                          "Catalogue-wide product requests in sales units, litres or kilograms. No orders are sent to Valio Aimo.")
bearer = HTTPBearer(auto_error=False)
_write_lock = threading.Lock()
_catalogue_cache = None
app.mount("/assets", StaticFiles(directory=ROOT / "static", check_dir=False), name="assets")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-store"})


def setting(name, default=""):
    return os.environ.get(name, default).strip()


def role(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    agent, reviewer = setting("AIMO_AGENT_TOKEN"), setting("AIMO_REVIEWER_TOKEN")
    if not agent or not reviewer or agent == reviewer:
        raise HTTPException(503, "Configure distinct AIMO_AGENT_TOKEN and AIMO_REVIEWER_TOKEN values.")
    if credentials and hmac.compare_digest(credentials.credentials, reviewer):
        return "reviewer"
    if credentials and hmac.compare_digest(credentials.credentials, agent):
        return "agent"
    raise HTTPException(401, "A valid local gateway Bearer token is required.", headers={"WWW-Authenticate": "Bearer"})


def can_review(identity: Annotated[str, Depends(role)]):
    if identity != "reviewer":
        raise HTTPException(403, "Only the reviewer credential can approve or reject.")
    return identity


def buyer():
    return setting("AIMO_CUSTOMER", "123")


def policy_limit():
    value = core.decimal_value(setting("AIMO_APPROVAL_LIMIT", "1200"))
    if value is None or value <= 0:
        raise HTTPException(503, "AIMO_APPROVAL_LIMIT must be a positive EUR amount.")
    return value


def db():
    connection = core.proposal_db(Path(setting("AIMO_DB", str(ROOT / "purchase_proposals.sqlite3"))))
    connection.execute("""CREATE TABLE IF NOT EXISTS gateway_offers
                       (id TEXT PRIMARY KEY, customer TEXT NOT NULL, expires_at TEXT NOT NULL, body TEXT NOT NULL)""")
    connection.execute("CREATE TABLE IF NOT EXISTS proposal_offer_links (proposal_id TEXT PRIMARY KEY, offer_id TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS mock_orders (id TEXT PRIMARY KEY, proposal_id TEXT UNIQUE NOT NULL, customer TEXT NOT NULL, body TEXT NOT NULL)")
    connection.commit()
    return connection


def catalogue():
    global _catalogue_cache
    if _catalogue_cache is None:
        path = Path(setting("AIMO_CATALOG", str(ROOT / core.CATALOG)))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError
            _catalogue_cache = data
        except (OSError, ValueError):
            raise HTTPException(503, "Catalogue unavailable. Set AIMO_CATALOG to the supplied product JSON.") from None
    return _catalogue_cache


def public_product(product):
    data = product.get("synkkaData", {})
    return {"sku": product["id"], "name": core.name_of(product),
            "sales_unit": product["salesUnit"], "base_unit": product["baseUnit"],
            "order_increment": "1" if core.decimal_value(product["allowedLotSize"]) == Decimal("0.01") else str(product["allowedLotSize"]),
            "claims": sorted({v["id"] for g in data.get("classifications", [])
                              if g.get("name") == "nutritionalClaim" for v in g.get("values", [])}),
            "labels": sorted({v["id"] for g in data.get("classifications", [])
                              if g.get("name") == "packagingMarkedLabel" for v in g.get("values", [])}),
            "supplier": product.get("vendorName"), "country_of_origin": product.get("countryOfOrigin")}


def strings(value):
    """Preserve decimal precision in public JSON: monetary/quantity values are strings."""
    return json.loads(json.dumps(value, default=lambda v: format(v, "f") if isinstance(v, Decimal) else str(v)))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OfferRequest(StrictModel):
    delivery_date: date
    litres: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3,
                                  description="Legacy milk request field; use quantity and unit for general products.")
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    unit: Literal["L", "KG", "SALES_UNIT"] = "L"
    query: str = Field(default="", max_length=120)
    plain_milk: bool | None = None
    required_claims: list[str] = Field(default_factory=list, max_length=20)
    required_origin: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    product_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)
    scan_offset: int = Field(default=0, ge=0, le=20000, description="Continue a catalogue query at next_scan_offset; not used with explicit product_ids.")

    @model_validator(mode="after")
    def consistent_quantity(self):
        if self.litres is not None and (self.quantity is not None or self.unit != "L"):
            raise ValueError("Use either litres or quantity/unit, not both.")
        return self

    def amount(self):
        return self.quantity if self.quantity is not None else self.litres if self.litres is not None else Decimal("1000")


class ProposalRequest(StrictModel):
    offer_id: str = Field(min_length=1, max_length=80)
    sku: str = Field(min_length=1, max_length=40)


class DecisionRequest(StrictModel):
    fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    note: str = Field(default="", max_length=1000)


class OrderRequest(StrictModel):
    proposal_id: str = Field(min_length=1, max_length=80)


class ProductView(BaseModel):
    sku: str
    name: str
    sales_unit: str
    base_unit: str
    order_increment: str
    claims: list[str]
    labels: list[str] = Field(default_factory=list)
    supplier: str | None = None
    country_of_origin: str | None = None


class ProductList(BaseModel):
    products: list[ProductView]
    limit: int
    scope: str


class BasketView(BaseModel):
    sku: str
    name: str
    sales_unit: str
    requested_litres: str | None
    requested_quantity: str | None = None
    requested_unit: str = "L"
    provided_quantity: str | None = None
    quantity: str | None
    litres: str | None
    net: str | None
    gross: str | None
    spend: str
    readiness: str
    reasons: list[str]
    warnings: list[str] = Field(default_factory=list)
    stock_status: str = "UNKNOWN"
    rule_version: str | None = None
    conversion_source: str
    litres_per_sales_unit: str | None
    quantity_per_sales_unit: str | None = None
    required_claims: list[str] = Field(default_factory=list)
    required_origin: str | None = None
    product_labels: list[str] = Field(default_factory=list)
    evidence: dict[str, str | None] = Field(default_factory=dict)
    selection_reason: str | None = None
    sales_unit_price_gross: str | None = None


class SearchSummary(BaseModel):
    match_count: int
    convertible_count: int
    missing_conversion_count: int
    searchable_count: int
    checked_count: int
    eligible_count: int
    scan_offset: int
    next_scan_offset: int | None
    scan_limit: int = 60


class OfferView(BaseModel):
    id: str
    customer: str
    delivery_date: str
    litres: str | None
    quantity: str | None = None
    unit: str = "L"
    query: str = ""
    approval_limit: str
    created_at: str
    expires_at: str
    options: list[BasketView]
    search_summary: SearchSummary | None = None


class PolicyView(BaseModel):
    customer: str
    approval_limit_eur_including_tax: str
    limit_basis: str
    stock_unknown_orderable_at_or_above: str
    rule_version: str
    order_submission_supported: bool
    mock_commit_supported: bool = True
    buyer_required_claims: list[str] = Field(default_factory=list)
    buyer_required_origin: str | None = None


class EventView(BaseModel):
    at: str
    action: str
    actor: str
    note: str
    snapshot_digest: str


class ProposalView(BaseModel):
    id: str
    fingerprint: str
    customer: str
    delivery_date: str
    basket: BasketView
    policy: dict[str, str]
    spending_status: str
    created_at: str
    expires_at: str
    expired: bool
    events: list[EventView]
    order_submitted: bool
    mock_order_id: str | None = None
    commitment_status: str = "NOT_COMMITTED"


class ProposalList(BaseModel):
    proposals: list[ProposalView]


class SessionView(BaseModel):
    role: str
    reviewer_name: str
    customer: str


class AlternativesView(BaseModel):
    offer_id: str | None
    options: list[BasketView]
    message: str
    created_at: str | None = None
    expires_at: str | None = None
    expired: bool = False


class OrderDraftLine(BaseModel):
    sku: str
    name: str
    quantity: str
    sales_unit: str
    net_eur: str
    gross_eur: str


class OrderDraftView(BaseModel):
    proposal_id: str
    fingerprint: str
    customer: str
    delivery_date: str
    spending_status: str
    expired: bool
    lines: list[OrderDraftLine]
    excluded_costs: list[str]
    evidence: dict[str, str | None]
    stock_status: str
    order_submitted: bool
    requires_fresh_validation_before_any_real_submission: bool


class MockOrderView(BaseModel):
    id: str
    proposal_id: str
    customer: str
    committed_at: str
    mode: Literal["MOCK_ONLY"]
    status: Literal["COMMITTED_MOCK"]
    spending_status: str
    approved_fingerprint: str
    delivery_date: str
    basket: BasketView
    revalidated_evidence: dict[str, str | None]
    revalidated_stock_status: str
    upstream_order_submitted: bool
    cost_scope: str


class MockOrderList(BaseModel):
    orders: list[MockOrderView]


@app.get("/session", operation_id="get_local_session", response_model=SessionView)
def session(identity: Annotated[str, Depends(role)]):
    return {"role": identity, "reviewer_name": setting("AIMO_REVIEWER_NAME", "local-reviewer"), "customer": buyer()}


@app.get("/health", operation_id="health")
def health():
    return {"status": "ok", "mode": "offline sample demo" if getattr(app.state,"offline_demo",False) else "local mock gateway", "orders_submitted": False}


@app.get("/policy", operation_id="get_policy", response_model=PolicyView)
def get_policy(identity: Annotated[str, Depends(role)]):
    return {"customer": buyer(), "approval_limit_eur_including_tax": str(policy_limit()),
            "limit_basis": "product subtotal; delivery fees and deposits excluded",
            "stock_unknown_orderable_at_or_above": "999999", "rule_version": core.RULE_VERSION,
            "order_submission_supported": False,
            "buyer_required_claims": sorted(c.strip() for c in setting("AIMO_REQUIRED_CLAIMS").split(",") if c.strip()),
            "buyer_required_origin": setting("AIMO_REQUIRED_ORIGIN") or None}


def requirements(request):
    # Buyer policy can make agent requests stricter, never weaker.
    mandatory = {c.strip() for c in setting("AIMO_REQUIRED_CLAIMS").split(",") if c.strip()}
    if request.plain_milk is True or (request.plain_milk is None and not request.query and not request.product_ids):
        mandatory.add("FREE_FROM_LACTOSE")
    if setting("AIMO_REQUIRED_ORIGIN") and request.required_origin and setting("AIMO_REQUIRED_ORIGIN") != request.required_origin:
        raise HTTPException(422, "Requested origin conflicts with buyer policy.")
    return {"required_claims": sorted(mandatory | set(request.required_claims)),
            "required_origin": setting("AIMO_REQUIRED_ORIGIN") or request.required_origin,
            "query": request.query}


def evaluate(product, price, stock, day, now, amount, limit, unit, rules, observed_at):
    option = core.basket_option(product, price, stock, day, now, amount, limit, {}, unit=unit)
    view = public_product(product)
    option["required_claims"] = rules.get("required_claims", [])
    option["required_origin"] = rules.get("required_origin")
    option["product_labels"] = view["labels"]
    for claim in option["required_claims"]:
        if claim not in view["claims"]:
            option["reasons"].append(f"Required claim {claim} is not explicitly recorded; unknown does not count as satisfied.")
            option["readiness"] = "BLOCKED"
    if option["required_origin"] and option["required_origin"] != product.get("countryOfOrigin"):
        option["reasons"].append("Required country of origin is missing or does not match.")
        option["readiness"] = "BLOCKED"
    catalog = (price or {}).get("catalogPrice") or {}
    gross = core.decimal_value(catalog.get("valueWithTax"))
    basis = core.decimal_value((price or {}).get("quantity"))
    option["sales_unit_price_gross"] = (gross / basis if gross is not None and basis is not None and basis > 0
                                       and catalog.get("currency") == "EUR" and (price or {}).get("error") is False else None)
    option["evidence"] = {"supplier": "Valio Aimo synthetic challenge backend", "price_endpoint": "/api/price",
        "availability_endpoint": "/api/availability", "upstream_availability_time": observed_at,
        "evaluated_at_utc": core.utc_now().isoformat(), "price_valid_from": catalog.get("validFrom"),
        "price_valid_to": catalog.get("validTo"), "available_date": ((stock or {}).get("scheduleLines") or [{}])[0].get("availableDate"),
        "closing_time": (stock or {}).get("closingTime"), "catalogue_last_updated": product.get("synkkaData", {}).get("lastUpdated"),
        "country_of_origin": product.get("countryOfOrigin"), "trust_limit": "Source observations over HTTPS; no independently verified credentials or guaranteed stock."}
    return option


def matches_query(product, query):
    text = " ".join(n.get("value", "") for n in product.get("synkkaData", {}).get("names", [])).casefold()
    # Word matching avoids 'pasta' matching Finnish compound words for paste.
    return all(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in query.casefold().split())


@app.get("/products", operation_id="search_products", response_model=ProductList)
def products(identity: Annotated[str, Depends(role)],
             q: str = Query(default="", max_length=100),
             lactose_free: bool = False, plain_milk: bool = False,
             limit: int = Query(default=10, ge=1, le=50)):
    source = catalogue()
    if plain_milk:
        source = core.shortlist(source, len(source))
    terms = q.casefold().split()
    result = []
    for p in source:
        if p.get("deleted"):
            continue
        view = public_product(p)
        if lactose_free and "FREE_FROM_LACTOSE" not in view["claims"]:
            continue
        search_text = " ".join(n.get("value", "") for n in p.get("synkkaData", {}).get("names", [])).casefold()
        if terms and not matches_query(p, q):
            continue
        result.append(view)
        if len(result) >= limit:
            break
    return {"products": result, "limit": limit, "scope": "static catalogue; prices queried separately"}


@app.post("/offers", operation_id="compare_product_offers", status_code=201, response_model=OfferView)
def offers(request: OfferRequest, identity: Annotated[str, Depends(role)]):
    if request.delivery_date < core.utc_now().date():
        raise HTTPException(422, "Delivery date cannot be in the past.")
    source = catalogue()
    rules = requirements(request)
    plain_milk = request.plain_milk if request.plain_milk is not None else not request.query and not request.product_ids
    allowed = core.shortlist(source, len(source)) if plain_milk else [p for p in source if not p.get("deleted")]
    if request.query:
        allowed = [p for p in allowed if matches_query(p, request.query)]
    if request.product_ids:
        if request.scan_offset:
            raise HTTPException(422, "scan_offset is for catalogue query searches, not explicit product_ids.")
        ids = set(request.product_ids)
        pool = [p for p in allowed if p["id"] in ids]
        if len(pool) != len(ids):
            raise HTTPException(422, "Requested SKU is missing, deleted or outside the query/plain-milk constraints.")
        match_count = len(pool)
        searchable_count = match_count
        convertible = sum(core.quantity_per_sales_unit(p, request.unit, {})[0] is not None for p in pool)
    else:
        # Static hard requirements first, before querying dynamic prices/stock.
        allowed = [p for p in allowed if all(c in public_product(p)["claims"] for c in rules["required_claims"])
                   and (not rules["required_origin"] or p.get("countryOfOrigin") == rules["required_origin"])]
        match_count = len(allowed)
        convertible = sum(core.quantity_per_sales_unit(p, request.unit, {})[0] is not None for p in allowed)
        compatible = [p for p in allowed if core.quantity_per_sales_unit(p, request.unit, {})[0] is not None]
        # No dynamic lookups for uncalculable products when compatible choices
        # exist. If none exist, show a small diagnostic set with per-pack prices.
        ranked = sorted(compatible or allowed[:20], key=lambda p: core.name_of(p).casefold())
        searchable_count = len(ranked)
        pool = ranked[request.scan_offset:request.scan_offset + 60]
    if not pool:
        raise HTTPException(422, "No catalogue products match the query and recorded requirements. Try a more specific product name or explicit SKUs.")
    key = setting("AIMO_API_KEY")
    if not key:
        raise HTTPException(503, "Set AIMO_API_KEY on the gateway server.")
    limit = policy_limit()
    selected, options = [], []
    prices, availability = {"products": []}, {"products": [], "productObservedAt": {}}
    for start in range(0, len(pool), 20):
        batch = pool[start:start + 20]
        payload = {"customer": buyer(), "requestedDate": request.delivery_date.isoformat(), "products": [p["id"] for p in batch]}
        try:
            price_batch = core.api_post("/api/price", payload, key)
            stock_batch = core.api_post("/api/availability", payload, key)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc).replace(key, "[REDACTED]")) from None
        prices.update({k: v for k, v in price_batch.items() if k != "products"})
        availability.update({k: v for k, v in stock_batch.items() if k != "products"})
        prices["products"].extend(price_batch["products"])
        availability["products"].extend(stock_batch["products"])
        availability["productObservedAt"].update({p["id"]: stock_batch.get("timeNow") for p in batch})
        price_map = {p["productId"]: p for p in price_batch["products"]}
        stock_map = {p["productId"]: p for p in stock_batch["products"]}
        now = core.stamp(stock_batch.get("timeNow")) or core.utc_now()
        options.extend(evaluate(p, price_map.get(p["id"]), stock_map.get(p["id"]), request.delivery_date, now,
                                request.amount(), limit, request.unit, rules, stock_batch.get("timeNow")) for p in batch)
        selected.extend(batch)
        if sum(o["readiness"].startswith("CHECKS PASSED") for o in options) >= 5:
            break
    options.sort(key=lambda o: (not o["readiness"].startswith("CHECKS PASSED"), o["gross"] is None, o["gross"] or Decimal(0)))
    next_offset = request.scan_offset + len(selected)
    summary = {"match_count": match_count, "convertible_count": convertible, "missing_conversion_count": match_count - convertible, "searchable_count": searchable_count,
               "checked_count": len(selected), "eligible_count": sum(o["readiness"].startswith("CHECKS PASSED") for o in options),
               "scan_offset": request.scan_offset, "next_scan_offset": next_offset if not request.product_ids and next_offset < searchable_count else None}
    created = core.utc_now()
    saved = strings({"id": "O-" + uuid.uuid4().hex[:12], "customer": buyer(),
                     "delivery_date": request.delivery_date.isoformat(), "litres": request.amount() if request.unit == "L" else None,
                     "quantity": request.amount(), "unit": request.unit, "query": request.query, "requirements": rules,
                     "approval_limit": limit, "created_at": created.isoformat(),
                     "expires_at": (created + timedelta(minutes=30)).isoformat(),
                     "options": options, "products": selected, "prices": prices, "availability": availability, "search_summary": summary})
    with closing(db()) as connection, connection:
        connection.execute("INSERT INTO gateway_offers VALUES (?,?,?,?)",
                           (saved["id"], buyer(), saved["expires_at"], json.dumps(saved)))
    return {k: saved[k] for k in ("id", "customer", "delivery_date", "litres", "quantity", "unit", "query", "approval_limit", "created_at", "expires_at", "options", "search_summary")}


def proposal_view(connection, pid):
    try:
        row, snapshot = core.load_proposal(connection, pid)
    except RuntimeError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 409, str(exc)) from None
    if snapshot["customer"] != buyer():
        raise HTTPException(404, "Proposal not found for this buyer.")
    order = connection.execute("SELECT id FROM mock_orders WHERE proposal_id=? AND customer=?", (pid, buyer())).fetchone()
    expired = core.utc_now() >= datetime.fromisoformat(row["expires_at"])
    commitment = ("COMMITTED_MOCK" if order else "REJECTED" if row["spending_status"] == "REJECTED"
                  else "EXPIRED" if expired else "AWAITING_HUMAN_APPROVAL" if row["spending_status"] == "PENDING"
                  else "AUTHORISED_AWAITING_COMMIT")
    return {"id": pid, "fingerprint": row["digest"], "customer": snapshot["customer"],
            "delivery_date": snapshot["delivery_date"], "basket": snapshot["basket"],
            "policy": snapshot["policy"], "spending_status": row["spending_status"],
            "created_at": row["created_at"], "expires_at": row["expires_at"],
            "expired": expired, "mock_order_id": order["id"] if order else None, "commitment_status": commitment,
            "events": [dict(e) for e in connection.execute("SELECT at,action,actor,note,snapshot_digest FROM proposal_events WHERE proposal_id=? ORDER BY sequence", (pid,))],
            "order_submitted": False}


@app.post("/proposals", operation_id="create_purchase_proposal", status_code=201, response_model=ProposalView)
def create_proposal(request: ProposalRequest, identity: Annotated[str, Depends(role)]):
    with _write_lock, closing(db()) as connection:
        row = connection.execute("SELECT * FROM gateway_offers WHERE id=? AND customer=?", (request.offer_id, buyer())).fetchone()
        if row is None:
            raise HTTPException(404, "Offer not found for this buyer.")
        saved = json.loads(row["body"])
        if core.utc_now() >= datetime.fromisoformat(row["expires_at"]):
            raise HTTPException(409, "Offer expired. Compare fresh offers.")
        if Decimal(saved["approval_limit"]) != policy_limit():
            raise HTTPException(409, "Purchasing policy changed. Compare fresh offers.")
        saved_rules = saved.get("requirements", {"required_claims": [], "required_origin": None})
        mandatory = {c.strip() for c in setting("AIMO_REQUIRED_CLAIMS").split(",") if c.strip()}
        if not mandatory.issubset(saved_rules["required_claims"]) or (setting("AIMO_REQUIRED_ORIGIN") and setting("AIMO_REQUIRED_ORIGIN") != saved_rules.get("required_origin")):
            raise HTTPException(409, "Buyer product requirements changed. Compare fresh offers.")
        option = next((o for o in saved["options"] if o["sku"] == request.sku), None)
        if option is None:
            raise HTTPException(422, "SKU is not in this offer.")
        if not option["readiness"].startswith("CHECKS PASSED"):
            raise HTTPException(409, {"message": "Basket is blocked or unresolved.", "reasons": option["reasons"]})
        product = next(p for p in saved["products"] if p["id"] == request.sku)
        # An ordering cut-off may pass during the offer review window. Recheck
        # the saved evidence against actual current time before saving a proposal.
        price = next(p for p in saved["prices"]["products"] if p["productId"] == request.sku)
        stock = next((p for p in saved["availability"]["products"] if p["productId"] == request.sku), None)
        amount = Decimal(saved.get("quantity") or saved["litres"])
        unit = saved.get("unit", "L")
        option = evaluate(product, price, stock, date.fromisoformat(saved["delivery_date"]), core.utc_now(),
                          amount, policy_limit(), unit, saved_rules,
                          saved["availability"].get("productObservedAt", {}).get(request.sku) or saved["availability"].get("timeNow"))
        if not option["readiness"].startswith("CHECKS PASSED"):
            raise HTTPException(409, {"message": "Basket conditions no longer pass.", "reasons": option["reasons"]})
        args = SimpleNamespace(customer=buyer(), date=date.fromisoformat(saved["delivery_date"]),
                               approval_limit=policy_limit(), policy_metadata={
                                   "required_claims": ",".join(saved_rules["required_claims"]),
                                   "required_origin": saved_rules.get("required_origin") or ""})
        eligible = [o for o in saved["options"] if o["readiness"].startswith("CHECKS PASSED") and o["gross"] is not None]
        cheapest = min((Decimal(o["gross"]) for o in eligible), default=None)
        option["selection_reason"] = ("Lowest tax-inclusive product subtotal among the checked eligible alternatives."
                                      if cheapest == option["gross"] else "Explicit selection from eligible alternatives; a lower-cost option may exist.")
        try:
            pid = core.save_proposal(connection, option, product, saved["prices"], saved["availability"], args)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None
        with connection:
            connection.execute("INSERT INTO proposal_offer_links VALUES (?,?)", (pid, saved["id"]))
        return proposal_view(connection, pid)


@app.get("/proposals", operation_id="list_proposals", response_model=ProposalList)
def list_proposals(identity: Annotated[str, Depends(role)], limit: int = Query(default=20, ge=1, le=100)):
    with closing(db()) as connection:
        # Local demo shares the CLI DB. Filter snapshots by configured buyer.
        ids = connection.execute("SELECT id,snapshot FROM proposals ORDER BY created_at DESC").fetchall()
        selected = [r["id"] for r in ids if json.loads(r["snapshot"])["customer"] == buyer()][:limit]
        return {"proposals": [proposal_view(connection, pid) for pid in selected]}


@app.get("/proposals/{pid}", operation_id="get_proposal", response_model=ProposalView)
def get_proposal(pid: str, identity: Annotated[str, Depends(role)]):
    with closing(db()) as connection:
        return proposal_view(connection, pid)


@app.get("/proposals/{pid}/alternatives", operation_id="get_proposal_alternatives", response_model=AlternativesView)
def proposal_alternatives(pid: str, identity: Annotated[str, Depends(role)]):
    with closing(db()) as connection:
        proposal_view(connection, pid)
        row = connection.execute("""SELECT o.body FROM gateway_offers o JOIN proposal_offer_links l
                         ON l.offer_id=o.id WHERE l.proposal_id=? AND o.customer=?""", (pid, buyer())).fetchone()
        if row is None:
            return {"offer_id": None, "options": [], "message": "No original comparison linked to this older proposal. Create a new comparison to see alternatives."}
        saved = json.loads(row["body"])
        return {"offer_id": saved["id"], "created_at": saved["created_at"], "expires_at": saved["expires_at"],
                "expired": core.utc_now() >= datetime.fromisoformat(saved["expires_at"]),
                "options": saved["options"], "message": "Original comparison snapshot; not a live stock check."}


@app.get("/proposals/{pid}/order-draft", operation_id="get_structured_order_draft", response_model=OrderDraftView)
def order_draft(pid: str, identity: Annotated[str, Depends(role)]):
    with closing(db()) as connection:
        proposal = proposal_view(connection, pid)
        basket = proposal["basket"]
        return {"proposal_id": pid, "fingerprint": proposal["fingerprint"], "customer": proposal["customer"],
                "delivery_date": proposal["delivery_date"], "spending_status": proposal["spending_status"],
                "expired": proposal["expired"],
                "lines": [{"sku": basket["sku"], "name": basket["name"], "quantity": basket["quantity"],
                           "sales_unit": basket["sales_unit"], "net_eur": basket["net"], "gross_eur": basket["gross"]}],
                "excluded_costs": ["delivery charges", "deposits"], "evidence": basket.get("evidence", {}),
                "stock_status": basket.get("stock_status", "UNKNOWN"), "order_submitted": False,
                "requires_fresh_validation_before_any_real_submission": True}


def check_commit_authority(connection, pid):
    proposal = proposal_view(connection, pid)
    if proposal["spending_status"] not in ("APPROVED", "AUTO_AUTHORISED", "WITHIN_LIMIT"):
        raise HTTPException(409, {"code": "HUMAN_APPROVAL_REQUIRED" if proposal["spending_status"] == "PENDING" else "NOT_AUTHORISED",
                                  "message": "The agent cannot commit this proposal without the required authority."})
    if proposal["expired"]:
        raise HTTPException(409, {"code": "PROPOSAL_EXPIRED", "message": "Compare fresh offers and obtain new authority."})
    if Decimal(proposal["policy"]["limit_eur_including_tax"]) != policy_limit():
        raise HTTPException(409, {"code": "POLICY_CHANGED", "message": "Create a proposal under current purchasing policy."})
    basket = proposal["basket"]
    mandatory = {c.strip() for c in setting("AIMO_REQUIRED_CLAIMS").split(",") if c.strip()}
    if not mandatory.issubset(basket.get("required_claims", [])) or (setting("AIMO_REQUIRED_ORIGIN") and setting("AIMO_REQUIRED_ORIGIN") != basket.get("required_origin")):
        raise HTTPException(409, {"code": "POLICY_CHANGED", "message": "Buyer product requirements changed."})
    if proposal["spending_status"] in ("AUTO_AUTHORISED", "WITHIN_LIMIT") and Decimal(basket["gross"]) > policy_limit():
        raise HTTPException(409, {"code": "HUMAN_APPROVAL_REQUIRED", "message": "Product subtotal exceeds autonomous authority."})
    return proposal


@app.post("/orders", operation_id="commit_mock_order", status_code=201, response_model=MockOrderView,
          responses={200: {"model": MockOrderView, "description": "Existing receipt returned for an idempotent retry"}})
def commit_order(request: OrderRequest, response: Response, identity: Annotated[str, Depends(role)]):
    """Local simulated commitment only. Never calls a supplier order endpoint."""
    with _write_lock, closing(db()) as connection:
        existing = connection.execute("SELECT body FROM mock_orders WHERE proposal_id=? AND customer=?", (request.proposal_id, buyer())).fetchone()
        if existing:
            response.status_code = 200
            return json.loads(existing["body"])
        proposal = check_commit_authority(connection, request.proposal_id)
        _, snapshot = core.load_proposal(connection, request.proposal_id)
        if not all(k in proposal["basket"] for k in ("requested_quantity", "requested_unit", "required_claims", "evidence")):
            raise HTTPException(409, {"code": "LEGACY_PROPOSAL", "message": "Create a fresh proposal with recorded requirements and source evidence before committing."})
        if date.fromisoformat(proposal["delivery_date"]) < core.utc_now().date():
            raise HTTPException(409, {"code": "DELIVERY_DATE_PASSED", "message": "Create a fresh proposal."})
        key = setting("AIMO_API_KEY")
        if not key:
            raise HTTPException(503, "Set AIMO_API_KEY for fresh price/availability validation.")
        payload = {"customer": buyer(), "requestedDate": proposal["delivery_date"], "products": [proposal["basket"]["sku"]]}
        try:
            prices = core.api_post("/api/price", payload, key)
            stock = core.api_post("/api/availability", payload, key)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc).replace(key, "[REDACTED]")) from None
        basket = proposal["basket"]
        price = next((p for p in prices["products"] if p["productId"] == basket["sku"]), None)
        availability = next((p for p in stock["products"] if p["productId"] == basket["sku"]), None)
        amount = Decimal(basket.get("requested_quantity") or basket.get("requested_litres"))
        # Use current catalogue attributes rather than silently trusting stale claims.
        product = next((p for p in catalogue() if p["id"] == basket["sku"] and not p.get("deleted")), None)
        if product is None:
            raise HTTPException(409, {"code": "PRODUCT_CHANGED", "message": "Product is no longer in the active catalogue."})
        current = evaluate(product, price, availability, date.fromisoformat(proposal["delivery_date"]), core.utc_now(),
                           amount, policy_limit(), basket.get("requested_unit", "L"),
                           {"required_claims": basket.get("required_claims", []), "required_origin": basket.get("required_origin")},
                           stock.get("timeNow"))
        def blocked(code, message):
            with connection:
                connection.execute("INSERT INTO proposal_events (proposal_id,at,action,actor,note,snapshot_digest) VALUES (?,?,?,?,?,?)",
                                   (request.proposal_id, core.utc_now().isoformat(), "COMMIT_BLOCKED", "purchasing-gateway",
                                    code + ": " + message, proposal["fingerprint"]))
            raise HTTPException(409, {"code": code, "message": message, "reasons": current["reasons"]})
        if not current["readiness"].startswith("CHECKS PASSED"):
            blocked("REVALIDATION_FAILED", "Fresh product, delivery or stock checks do not pass; no order committed.")
        # Approval binds exact commercial values; even a lower price needs a new proposal.
        numeric = ("quantity", "net", "gross", "litres_per_sales_unit")
        changed = any(core.decimal_value(current.get(k)) != core.decimal_value(basket.get(k)) for k in numeric)
        changed = changed or current["sales_unit"] != basket["sales_unit"]
        if basket.get("quantity_per_sales_unit") is not None:
            changed = changed or core.decimal_value(current.get("quantity_per_sales_unit")) != core.decimal_value(basket["quantity_per_sales_unit"])
        if changed:
            blocked("OFFER_CHANGED_REAPPROVAL_REQUIRED", "Basket price, quantity or unit conversion changed. Compare fresh offers and obtain authority again.")
        receipt = strings({"id": "M-" + uuid.uuid4().hex[:12], "proposal_id": request.proposal_id, "customer": buyer(),
            "committed_at": core.utc_now().isoformat(), "mode": "MOCK_ONLY", "status": "COMMITTED_MOCK",
            "spending_status": proposal["spending_status"], "approved_fingerprint": proposal["fingerprint"],
            "delivery_date": proposal["delivery_date"], "basket": basket,
            "revalidated_evidence": current["evidence"], "revalidated_stock_status": current["stock_status"],
            "upstream_order_submitted": False, "cost_scope": "Synthetic product subtotal only; delivery charges and deposits excluded."})
        try:
            connection.execute("BEGIN IMMEDIATE")
            # Final atomic authority check also protects against a separate CLI
            # process changing proposal state while upstream queries were running.
            latest = check_commit_authority(connection, request.proposal_id)
            if latest["fingerprint"] != proposal["fingerprint"]:
                raise HTTPException(409, "Proposal changed during revalidation.")
            existing = connection.execute("SELECT body FROM mock_orders WHERE proposal_id=? AND customer=?", (request.proposal_id, buyer())).fetchone()
            if existing:
                connection.rollback()
                response.status_code = 200
                return json.loads(existing["body"])
            connection.execute("INSERT INTO mock_orders VALUES (?,?,?,?)", (receipt["id"], request.proposal_id, buyer(), json.dumps(receipt)))
            connection.execute("INSERT INTO proposal_events (proposal_id,at,action,actor,note,snapshot_digest) VALUES (?,?,?,?,?,?)",
                               (request.proposal_id, receipt["committed_at"], "COMMITTED_MOCK", "purchasing-gateway",
                                "Mock receipt " + receipt["id"] + "; fresh price and availability passed. No supplier order sent.", proposal["fingerprint"]))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return receipt


@app.get("/orders", operation_id="list_mock_orders", response_model=MockOrderList)
def list_orders(identity: Annotated[str, Depends(role)], limit: int = Query(default=20, ge=1, le=100)):
    with closing(db()) as connection:
        rows = connection.execute("SELECT body FROM mock_orders WHERE customer=? ORDER BY rowid DESC LIMIT ?", (buyer(), limit)).fetchall()
        return {"orders": [json.loads(r["body"]) for r in rows]}


@app.get("/orders/{oid}", operation_id="get_mock_order", response_model=MockOrderView)
def get_order(oid: str, identity: Annotated[str, Depends(role)]):
    with closing(db()) as connection:
        row = connection.execute("SELECT body FROM mock_orders WHERE id=? AND customer=?", (oid, buyer())).fetchone()
        if row is None:
            raise HTTPException(404, "Mock order not found for this buyer.")
        return json.loads(row["body"])


def decision(pid, request, status):
    if status == "REJECTED" and not request.note.strip():
        raise HTTPException(422, "A rejection note is required.")
    with _write_lock, closing(db()) as connection:
        saved = proposal_view(connection, pid)  # Buyer scope and integrity check.
        if Decimal(saved["policy"]["limit_eur_including_tax"]) != policy_limit():
            raise HTTPException(409, "Purchasing policy changed. Create a fresh proposal.")
        mandatory = {c.strip() for c in setting("AIMO_REQUIRED_CLAIMS").split(",") if c.strip()}
        if not mandatory.issubset(set(saved["basket"].get("required_claims", []))) or (setting("AIMO_REQUIRED_ORIGIN") and setting("AIMO_REQUIRED_ORIGIN") != saved["basket"].get("required_origin")):
            raise HTTPException(409, "Buyer product requirements changed. Create a fresh proposal.")
        try:
            core.decide_proposal(connection, pid, status, setting("AIMO_REVIEWER_NAME", "local-reviewer"),
                                 request.note, request.fingerprint)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None
        return proposal_view(connection, pid)


@app.post("/proposals/{pid}/approve", operation_id="approve_spending", response_model=ProposalView)
def approve(pid: str, request: DecisionRequest, identity: Annotated[str, Depends(can_review)]):
    return decision(pid, request, "APPROVED")


@app.post("/proposals/{pid}/reject", operation_id="reject_spending", response_model=ProposalView)
def reject(pid: str, request: DecisionRequest, identity: Annotated[str, Depends(can_review)]):
    return decision(pid, request, "REJECTED")


import sys
from recipe_agent import install_recipe_routes
install_recipe_routes(app, sys.modules[__name__])
from vapi_bridge import install_voice_routes
install_voice_routes(app, sys.modules[__name__])

if __name__ == "__main__":
    for name in ("AIMO_AGENT_TOKEN", "AIMO_REVIEWER_TOKEN"):
        if not setting(name):
            os.environ[name] = secrets.token_urlsafe(24)
            print(f"{name}={os.environ[name]}", flush=True)
    print("Reviewer dashboard: http://127.0.0.1:8000", flush=True)
    print("API reference: http://127.0.0.1:8000/docs", flush=True)
    print("Keep the reviewer token separate from the agent. Tokens shown above are local demo credentials.", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8000, workers=1)
