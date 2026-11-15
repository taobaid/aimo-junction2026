"""Offline integration tests. python -m unittest -v test_api"""
from contextlib import closing
from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
import httpx
from unittest.mock import patch
from fastapi.testclient import TestClient
import aimo_api as gateway


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "AIMO_RECIPE_CACHE":"0", "AIMO_AGENT_TOKEN": "agent-test", "AIMO_REVIEWER_TOKEN": "reviewer-test",
            "AIMO_API_KEY": "mock-upstream-test", "AIMO_DB": str(Path(self.temp.name) / "test.sqlite3"),
            "AIMO_CUSTOMER": "123", "AIMO_APPROVAL_LIMIT": "1200", "AIMO_REVIEWER_NAME": "Test reviewer"})
        self.env.start()
        self.now = gateway.core.utc_now()
        self.day = (self.now + timedelta(days=3)).date().isoformat()
        gateway._catalogue_cache = [{"id": "464201", "salesUnit": "ST", "baseUnit": "ST",
            "allowedLotSize": 0.01, "units": [{"unitId": "ST", "sizeInBaseUnits": 1}],
            "synkkaData": {"names": [{"language": "en", "value": "Valio semi skimmed milk 1 l lactose free UHT"}],
                "classifications": [{"name": "nutritionalClaim", "values": [{"id": "FREE_FROM_LACTOSE"}]}],
                "unitConversions": [{"synkkaPackagingType": "BASE_UNIT_OR_EACH", "volume": {"unit": "LTR", "value": 1}}]}}]
        self.stock_amount = 9999999999
        self.price_factor = 1
        self.upstream = patch.object(gateway.core, "api_post", side_effect=self.mock_upstream)
        self.upstream.start()
        self.client = TestClient(gateway.app)
        self.agent = {"Authorization": "Bearer agent-test"}
        self.reviewer = {"Authorization": "Bearer reviewer-test"}

    def tearDown(self):
        self.client.close()
        self.upstream.stop()
        gateway._catalogue_cache = None
        self.env.stop()
        self.temp.cleanup()

    def mock_upstream(self, endpoint, payload, key):
        if endpoint == "/api/price":
            return {"products": [{"productId": pid, "error": False, "quantity": 1,
                "catalogPrice": {"value": (1.56 if pid == "464201" else 20) * self.price_factor,
                    "valueWithTax": (1.77 if pid == "464201" else 22.7) * self.price_factor, "currency": "EUR",
                    "validFrom": self.now.date().isoformat(), "validTo": self.day}} for pid in payload["products"]]}
        units = {p["id"]: p["salesUnit"] for p in gateway._catalogue_cache}
        return {"timeNow": self.now.isoformat(), "products": [{"productId": pid, "salesBlock": False,
            "logisticModel": "Terminal", "closingTime": (self.now + timedelta(days=1)).isoformat(),
            "scheduleLines": [{"salesBlock": False, "salesUnit": units[pid], "availableDate": self.day,
                               "availableAmount": self.stock_amount}]} for pid in payload["products"]]}

    def offer(self):
        response = self.client.post("/offers", headers=self.agent, json={"delivery_date": self.day, "litres": "1000"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def proposal(self):
        offer = self.offer()
        response = self.client.post("/proposals", headers=self.agent, json={"offer_id": offer["id"], "sku": "464201"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_search_auth_and_schema(self):
        self.assertEqual(self.client.get("/products").status_code, 401)
        result = self.client.get("/products?plain_milk=true", headers=self.agent)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["products"][0]["order_increment"], "1")
        self.assertIn("BasketView", self.client.get("/openapi.json").json()["components"]["schemas"])

    def test_dashboard_and_role(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn("Kitchen purchasing", self.client.get("/").text)
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)
        self.assertEqual(self.client.get("/session", headers=self.agent).json()["role"], "agent")
        self.assertEqual(self.client.get("/session", headers=self.reviewer).json()["role"], "reviewer")

    def test_original_alternatives_linked(self):
        proposal = self.proposal()
        result = self.client.get(f"/proposals/{proposal['id']}/alternatives", headers=self.reviewer)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["options"][0]["sku"], "464201")
        self.assertIn("snapshot", result.json()["message"])

    def test_offer_and_proposal_approval(self):
        proposal = self.proposal()
        self.assertEqual(proposal["basket"]["gross"], "1770.00")
        self.assertEqual(proposal["basket"]["stock_status"], "UNKNOWN_ORDERABLE")
        self.assertEqual(proposal["spending_status"], "PENDING")
        pid = proposal["id"]
        body = {"fingerprint": proposal["fingerprint"]}
        self.assertEqual(self.client.post(f"/proposals/{pid}/approve", headers=self.agent, json=body).status_code, 403)
        accepted = self.client.post(f"/proposals/{pid}/approve", headers=self.reviewer, json=body)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["spending_status"], "APPROVED")
        self.assertEqual(accepted.json()["basket"]["stock_status"], "UNKNOWN_ORDERABLE")
        self.assertFalse(accepted.json()["order_submitted"])
        self.assertEqual(len(accepted.json()["events"]), 2)
        self.assertEqual(self.client.post(f"/proposals/{pid}/approve", headers=self.reviewer, json=body).status_code, 409)

    def test_tampered_fingerprint_and_rejection(self):
        proposal = self.proposal(); pid = proposal["id"]
        self.assertEqual(self.client.post(f"/proposals/{pid}/approve", headers=self.reviewer,
                         json={"fingerprint": "0" * 64}).status_code, 409)
        body = {"fingerprint": proposal["fingerprint"], "note": "Over budget"}
        result = self.client.post(f"/proposals/{pid}/reject", headers=self.reviewer, json=body)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["spending_status"], "REJECTED")

    def test_agent_cannot_supply_policy_or_price(self):
        self.assertEqual(self.client.post("/offers", headers=self.agent,
            json={"delivery_date": self.day, "approval_limit": 99999}).status_code, 422)
        self.assertEqual(self.client.post("/proposals", headers=self.agent,
            json={"offer_id": "fake", "sku": "464201", "gross": "1.00"}).status_code, 422)

    def test_blocked_stock_cannot_be_proposed(self):
        self.stock_amount = 0
        offer = self.offer()
        self.assertEqual(offer["options"][0]["readiness"], "BLOCKED")
        self.assertEqual(self.client.post("/proposals", headers=self.agent,
            json={"offer_id": offer["id"], "sku": "464201"}).status_code, 409)

    def test_expiry_and_buyer_scope(self):
        proposal = self.proposal(); pid = proposal["id"]
        with closing(gateway.db()) as connection, connection:
            connection.execute("UPDATE proposals SET expires_at=? WHERE id=?",
                               ((self.now - timedelta(minutes=1)).isoformat(), pid))
        self.assertEqual(self.client.post(f"/proposals/{pid}/approve", headers=self.reviewer,
                         json={"fingerprint": proposal["fingerprint"]}).status_code, 409)
        os.environ["AIMO_CUSTOMER"] = "other"
        self.assertEqual(self.client.get(f"/proposals/{pid}", headers=self.agent).status_code, 404)
        self.assertEqual(self.client.get("/proposals", headers=self.agent).json()["proposals"], [])

    def test_changed_policy_and_offer_expiry(self):
        offer = self.offer()
        os.environ["AIMO_APPROVAL_LIMIT"] = "1000"
        self.assertEqual(self.client.post("/proposals", headers=self.agent,
            json={"offer_id": offer["id"], "sku": "464201"}).status_code, 409)

        os.environ["AIMO_APPROVAL_LIMIT"] = "1200"
        with closing(gateway.db()) as connection, connection:
            connection.execute("UPDATE gateway_offers SET expires_at=? WHERE id=?",
                               ((self.now - timedelta(minutes=1)).isoformat(), offer["id"]))
        self.assertEqual(self.client.post("/proposals", headers=self.agent,
            json={"offer_id": offer["id"], "sku": "464201"}).status_code, 409)

    def add_pasta(self):
        gateway._catalogue_cache.append({"id": "PASTA", "salesUnit": "SK", "baseUnit": "SK",
            "allowedLotSize": 0.01, "countryOfOrigin": "fi", "units": [{"unitId": "SK", "sizeInBaseUnits": 1}],
            "synkkaData": {"names": [{"language": "en", "value": "Test macaroni 10kg"}],
                          "classifications": [], "unitConversions": [{"synkkaPackagingType": "BASE_UNIT_OR_EACH", "netWeight": {"unit": "KGM", "value": 10}}]}})

    def test_general_product_kilograms_and_autonomy(self):
        self.add_pasta()
        offer = self.client.post("/offers", headers=self.agent, json={"query": "macaroni", "quantity": "100", "unit": "KG", "delivery_date": self.day})
        self.assertEqual(offer.status_code, 201, offer.text)
        result = offer.json(); option = result["options"][0]
        self.assertEqual(option["quantity"], "10")
        self.assertEqual(option["provided_quantity"], "100")
        self.assertIsNone(option["litres"])
        self.assertEqual(option["gross"], "227.00")
        response = self.client.post("/proposals", headers=self.agent, json={"offer_id": result["id"], "sku": "PASTA"})
        self.assertEqual(response.status_code, 201, response.text)
        proposal = response.json()
        self.assertEqual(proposal["spending_status"], "AUTO_AUTHORISED")
        self.assertEqual(proposal["events"][-1]["action"], "AUTO_AUTHORISED")
        draft = self.client.get(f"/proposals/{proposal['id']}/order-draft", headers=self.agent).json()
        self.assertEqual(draft["lines"][0]["quantity"], "10")
        self.assertFalse(draft["order_submitted"])

    def test_general_sales_units(self):
        self.add_pasta()
        response = self.client.post("/offers", headers=self.agent, json={"product_ids": ["PASTA"], "quantity": "3.2", "unit": "SALES_UNIT", "delivery_date": self.day})
        self.assertEqual(response.status_code, 201, response.text)
        option = response.json()["options"][0]
        self.assertEqual(option["quantity"], "4")
        self.assertEqual(option["provided_quantity"], "4")

    def test_required_claim_cannot_be_assumed(self):
        self.add_pasta()
        response = self.client.post("/offers", headers=self.agent, json={"product_ids": ["PASTA"], "quantity": "10", "unit": "KG", "delivery_date": self.day, "required_claims": ["FREE_FROM_GLUTEN"]})
        self.assertEqual(response.status_code, 201)
        result = response.json()
        self.assertEqual(result["options"][0]["readiness"], "BLOCKED")
        self.assertEqual(self.client.post("/proposals", headers=self.agent, json={"offer_id": result["id"], "sku": "PASTA"}).status_code, 409)

    def test_origin_and_buyer_policy_enforced(self):
        self.add_pasta()
        os.environ["AIMO_REQUIRED_ORIGIN"] = "fi"
        response = self.client.post("/offers", headers=self.agent, json={"query": "macaroni", "quantity": "10", "unit": "KG", "delivery_date": self.day, "required_origin": "de"})
        self.assertEqual(response.status_code, 422)
        os.environ["AIMO_REQUIRED_CLAIMS"] = "FREE_FROM_GLUTEN"
        response = self.client.post("/offers", headers=self.agent, json={"product_ids": ["PASTA"], "quantity": "10", "unit": "SALES_UNIT", "delivery_date": self.day})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["options"][0]["readiness"], "BLOCKED")

    def test_unknown_conversion_and_variable_weight(self):
        self.add_pasta()
        gateway._catalogue_cache[-1]["synkkaData"]["variableUnit"] = True
        response = self.client.post("/offers", headers=self.agent, json={"query": "macaroni", "quantity": "10", "unit": "KG", "delivery_date": self.day})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["options"][0]["readiness"], "NEEDS REVIEW")
        self.assertIsNone(response.json()["options"][0]["quantity"])

    def test_quantity_conflicts_rejected(self):
        response = self.client.post("/offers", headers=self.agent, json={"delivery_date": self.day, "litres": "1000", "quantity": "1"})
        self.assertEqual(response.status_code, 422)

    def test_llm_tool_loop_with_mock_provider(self):
        import llm_agent
        step = [0]
        def model_reply(request):
            body = json.loads(request.content)
            phase = step[0]; step[0] += 1
            if phase == 0:
                name, arguments = "read_policy", {}
            elif phase == 1:
                name, arguments = "search_products", {"plain_milk": True, "limit": 5}
            elif phase == 2:
                name, arguments = "compare_offers", {"delivery_date": self.day, "quantity": "1000", "unit": "L", "plain_milk": True}
            else:
                previous = json.loads(body["messages"][-1]["content"])
                name, arguments = "create_proposal", {"offer_id": previous["id"], "sku": "464201"}
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "call-" + str(phase), "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]})
        self.client.headers.update(self.agent)
        with httpx.Client(base_url="https://fixture.invalid/v1/", transport=httpx.MockTransport(model_reply)) as model:
            result = llm_agent.run_agent("Buy 1000 litres of lactose-free milk", self.client, model, "fixture-model")
        self.assertEqual(step[0], 4)
        self.assertEqual(result["proposal"]["spending_status"], "PENDING")
        self.assertFalse(result["proposal"]["order_submitted"])

    def test_llm_client_refuses_reviewer_credential(self):
        import llm_agent
        self.client.headers.update(self.reviewer)
        with self.assertRaisesRegex(RuntimeError, "AGENT token"):
            llm_agent.run_agent("Buy milk", self.client, None, "fixture-model")

    def approve_proposal(self, proposal):
        response = self.client.post(f"/proposals/{proposal['id']}/approve", headers=self.reviewer,
                                    json={"fingerprint": proposal["fingerprint"]})
        self.assertEqual(response.status_code, 200, response.text)

    def test_pending_order_commit_denied(self):
        proposal = self.proposal()
        with patch.object(gateway.core, "api_post", side_effect=AssertionError("Must check permission before upstream calls")):
            response = self.client.post("/orders", headers=self.agent, json={"proposal_id": proposal["id"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "HUMAN_APPROVAL_REQUIRED")

    def test_approved_order_and_idempotent_receipt(self):
        proposal = self.proposal(); self.approve_proposal(proposal)
        response = self.client.post("/orders", headers=self.agent, json={"proposal_id": proposal["id"]})
        self.assertEqual(response.status_code, 201, response.text)
        receipt = response.json()
        self.assertEqual(receipt["status"], "COMMITTED_MOCK")
        self.assertFalse(receipt["upstream_order_submitted"])
        self.assertEqual(receipt["approved_fingerprint"], proposal["fingerprint"])
        self.stock_amount = 0
        with patch.object(gateway.core, "api_post", side_effect=AssertionError("Replay must not create/revalidate another order")):
            replay = self.client.post("/orders", headers=self.agent, json={"proposal_id": proposal["id"]})
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), receipt)
        refreshed = self.client.get(f"/proposals/{proposal['id']}", headers=self.agent).json()
        self.assertEqual(refreshed["mock_order_id"], receipt["id"])
        self.assertEqual(refreshed["events"][-1]["action"], "COMMITTED_MOCK")
        self.assertEqual(len(self.client.get("/orders", headers=self.agent).json()["orders"]), 1)

    def test_autonomous_order_commit(self):
        offer = self.client.post("/offers", headers=self.agent, json={"delivery_date": self.day, "litres": "100"}).json()
        proposal = self.client.post("/proposals", headers=self.agent, json={"offer_id": offer["id"], "sku": "464201"}).json()
        self.assertEqual(proposal["spending_status"], "AUTO_AUTHORISED")
        response = self.client.post("/orders", headers=self.agent, json={"proposal_id": proposal["id"]})
        self.assertEqual(response.status_code, 201, response.text)

    def test_price_change_requires_new_authority(self):
        proposal = self.proposal(); self.approve_proposal(proposal); self.price_factor = 2
        response = self.client.post("/orders", headers=self.agent, json={"proposal_id": proposal["id"]})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "OFFER_CHANGED_REAPPROVAL_REQUIRED")
        self.assertEqual(self.client.get("/orders", headers=self.agent).json()["orders"], [])
        refreshed = self.client.get(f"/proposals/{proposal['id']}", headers=self.agent).json()
        self.assertEqual(refreshed["events"][-1]["action"], "COMMIT_BLOCKED")

    def test_stock_change_prevents_commit(self):
        proposal = self.proposal(); self.approve_proposal(proposal); self.stock_amount = 0
        response = self.client.post("/orders", headers=self.agent, json={"proposal_id": proposal["id"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "REVALIDATION_FAILED")
        self.assertEqual(self.client.get("/orders", headers=self.agent).json()["orders"], [])

    def test_order_expiry_policy_and_buyer_scope(self):
        proposal = self.proposal(); self.approve_proposal(proposal)
        os.environ["AIMO_APPROVAL_LIMIT"] = "1000"
        self.assertEqual(self.client.post("/orders", headers=self.agent, json={"proposal_id": proposal["id"]}).status_code, 409)
        os.environ["AIMO_APPROVAL_LIMIT"] = "1200"
        with closing(gateway.db()) as connection, connection:
            connection.execute("UPDATE proposals SET expires_at=? WHERE id=?", ((self.now - timedelta(minutes=1)).isoformat(), proposal["id"]))
        self.assertEqual(self.client.post("/orders", headers=self.agent, json={"proposal_id": proposal["id"]}).status_code, 409)
        os.environ["AIMO_CUSTOMER"] = "other"
        self.assertEqual(self.client.post("/orders", headers=self.agent, json={"proposal_id": proposal["id"]}).status_code, 404)

    def test_current_claims_revalidated_before_commit(self):
        proposal = self.proposal(); self.approve_proposal(proposal)
        gateway._catalogue_cache[0]["synkkaData"]["classifications"] = []
        response = self.client.post("/orders", headers=self.agent, json={"proposal_id": proposal["id"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "REVALIDATION_FAILED")

    def test_order_receipt_and_audit_are_atomic(self):
        proposal = self.proposal(); self.approve_proposal(proposal)
        with closing(gateway.db()) as connection, connection:
            connection.execute("""CREATE TRIGGER fail_commit_event BEFORE INSERT ON proposal_events
                           WHEN NEW.action='COMMITTED_MOCK' BEGIN SELECT RAISE(ABORT,'test audit failure'); END""")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.client.post("/orders", headers=self.agent, json={"proposal_id": proposal["id"]})
        self.assertEqual(self.client.get("/orders", headers=self.agent).json()["orders"], [])

    def test_llm_autonomous_mock_commit_with_mock_provider(self):
        import llm_agent
        phase = [0]
        def model_reply(request):
            body = json.loads(request.content); step = phase[0]; phase[0] += 1
            if step == 0: name, arguments = "read_policy", {}
            elif step == 1: name, arguments = "search_products", {"plain_milk": True}
            elif step == 2: name, arguments = "compare_offers", {"delivery_date": self.day, "quantity": "100", "unit": "L", "plain_milk": True}
            elif step == 3:
                previous = json.loads(body["messages"][-1]["content"])
                name, arguments = "create_proposal", {"offer_id": previous["id"], "sku": "464201"}
            else:
                previous = json.loads(body["messages"][-1]["content"])
                name, arguments = "place_mock_order", {"proposal_id": previous["id"]}
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "call-" + str(step), "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]})
        self.client.headers.update(self.agent)
        with httpx.Client(base_url="https://fixture.invalid/v1/", transport=httpx.MockTransport(model_reply)) as provider:
            result = llm_agent.run_agent("Order 100 litres of lactose-free milk", self.client, provider, "fixture-model")
        self.assertEqual(phase[0], 5)
        self.assertEqual(result["order"]["status"], "COMMITTED_MOCK")
        self.assertFalse(result["order"]["upstream_order_submitted"])

    def test_case_weight_is_not_multiplied_twice(self):
        product = {"id": "CASE", "salesUnit": "KI", "baseUnit": "BAG", "salesUnitGtin": "case-gtin", "allowedLotSize": .01,
                   "units": [{"unitId": "KI", "gtin": "case-gtin", "sizeInBaseUnits": 15}, {"unitId": "BAG", "sizeInBaseUnits": 1}],
                   "synkkaData": {"names": [{"language": "en", "value": "15 x Test pasta 500g"}], "classifications": [],
                                  "unitConversions": [{"synkkaPackagingType": "CASE", "netWeight": {"unit": "GRM", "value": 7500}, "grossWeight": {"unit": "GRM", "value": 7700}}]}}
        gateway._catalogue_cache.append(product)
        factor, _ = gateway.core.quantity_per_sales_unit(product, "KG", {})
        self.assertEqual(str(factor), "7.500")
        response = self.client.post("/offers", headers=self.agent, json={"product_ids": ["CASE"], "quantity": "100", "unit": "KG", "delivery_date": self.day})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["options"][0]["quantity"], "14")
        product["synkkaData"]["unitConversions"][0].pop("netWeight")
        self.assertIsNone(gateway.core.quantity_per_sales_unit(product, "KG", {})[0])
        product["synkkaData"]["unitConversions"][0]["netWeight"] = {"unit": "GRM", "value": 7500}
        product["units"][0]["sizeInBaseUnits"] = 12
        self.assertIsNone(gateway.core.quantity_per_sales_unit(product, "KG", {})[0])

    def test_conversion_compatible_products_are_shortlisted_first(self):
        self.add_pasta()
        gateway._catalogue_cache[-1]["synkkaData"]["names"][0]["value"] = "ZZ pasta with net weight"
        for i in range(25):
            p = json.loads(json.dumps(gateway._catalogue_cache[-1])); p["id"] = f"NO-KG-{i}"
            p["synkkaData"]["names"][0]["value"] = f"AA pasta without measurement {i}"
            p["synkkaData"]["unitConversions"] = []
            gateway._catalogue_cache.append(p)
        result = self.client.post("/offers", headers=self.agent, json={"query": "pasta", "quantity": "100", "unit": "KG", "plain_milk": False, "delivery_date": self.day}).json()
        self.assertEqual(result["search_summary"]["match_count"], 26)
        self.assertEqual(result["search_summary"]["checked_count"], 1)
        self.assertEqual(result["options"][0]["sku"], "PASTA")
        self.assertTrue(result["options"][0]["readiness"].startswith("CHECKS PASSED"))

    def test_search_continues_after_first_twenty_unavailable(self):
        self.add_pasta(); template = gateway._catalogue_cache.pop()
        for i in range(25):
            product = json.loads(json.dumps(template)); product["id"] = f"BULK-{i:02}"
            product["synkkaData"]["names"][0]["value"] = f"Pasta {i:02}"
            gateway._catalogue_cache.append(product)
        calls = []
        def batch_upstream(endpoint, payload, key):
            calls.append((endpoint, payload["products"]))
            result = self.mock_upstream(endpoint, payload, key)
            if endpoint == "/api/availability":
                for item in result["products"]:
                    if int(item["productId"].split("-")[-1]) < 20:
                        item["scheduleLines"][0]["availableAmount"] = 0
            return result
        with patch.object(gateway.core, "api_post", side_effect=batch_upstream):
            response = self.client.post("/offers", headers=self.agent, json={"query": "pasta", "quantity": "100", "unit": "KG", "delivery_date": self.day})
        self.assertEqual(response.status_code, 201)
        result = response.json()
        self.assertEqual(result["search_summary"]["checked_count"], 25)
        self.assertEqual(result["search_summary"]["eligible_count"], 5)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(len(ids) <= 20 for _,ids in calls))
        self.assertTrue(result["options"][0]["readiness"].startswith("CHECKS PASSED"))

    def test_pasta_query_does_not_match_compound_word_for_paste(self):
        paste = {"synkkaData": {"names": [{"language": "en", "value": "Harissa paste"}, {"language": "fi", "value": "chilipasta"}]}}
        self.assertFalse(gateway.matches_query(paste, "pasta"))
        self.assertTrue(gateway.matches_query(paste, "paste"))

    def test_query_scan_offset_returns_next_candidates(self):
        self.add_pasta(); template = gateway._catalogue_cache.pop()
        for i in range(25):
            p=json.loads(json.dumps(template));p["id"]=f"SCAN-{i:02}";p["synkkaData"]["names"][0]["value"]=f"Pasta {i:02}"
            gateway._catalogue_cache.append(p)
        payload={"query":"pasta","quantity":"1","unit":"KG","delivery_date":self.day}
        first=self.client.post("/offers",headers=self.agent,json=payload).json()
        self.assertEqual(first["search_summary"]["next_scan_offset"],20)
        next_result=self.client.post("/offers",headers=self.agent,json={**payload,"scan_offset":20}).json()
        self.assertEqual(next_result["search_summary"]["checked_count"],5)
        self.assertIsNone(next_result["search_summary"]["next_scan_offset"])
        self.assertTrue(set(o["sku"] for o in first["options"]).isdisjoint(o["sku"] for o in next_result["options"]))



if __name__ == "__main__":
    unittest.main()
