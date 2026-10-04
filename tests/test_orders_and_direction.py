"""The demo orders, the direction check (code) and the customer's own choice."""

import asyncio

import pytest
from fastapi.testclient import TestClient

import main
import orders
import returns
import store
from test_api import GOOD, client, sarvam  # noqa: F401  (fixtures)
from test_returns import FakeLLM, out, run
from test_store import analyse


# --- direction check ---------------------------------------------------------

@pytest.mark.parametrize("text,code,conflict", [
    ("The dress is too tight around my waist.", "LOOSE_AT_WAIST", True),        # the known failure
    ("Kamar pe bahut tight hai", "SIZE_TOO_LARGE", True),
    ("कमर पर बहुत टाइट है", "LOOSE_AT_WAIST", True),
    ("Maine medium size order kiya tha lekin bahut loose hai.", "SIZE_TOO_LARGE", False),
    ("Size loose hai and stitching bhi open ho rahi hai.", "SIZE_TOO_LARGE", False),
    ("too tight around my waist", "SIZE_TOO_SMALL", False),
    ("Length bahut lambi hai", "LENGTH_TOO_SHORT", True),
    ("Sleeves chhoti hain", "SLEEVES_TOO_LONG", True),
    ("tight at the chest but loose at the waist", "LOOSE_AT_WAIST", False),    # both sides: ambiguous, left alone
    ("Colour photo jaisa nahi hai", "COLOUR_NOT_MATCHING", False),             # no direction to check
    ("I don't like it", "UNCLEAR_FREE_TEXT", False),
])
def test_direction_conflict(text, code, conflict):
    assert returns.direction_conflict(text, code) is conflict


def test_confident_wrong_direction_asks_the_customer_to_confirm():
    # The model is sure (1.0) and wrong. Code, not confidence, catches it. The reason is not changed.
    result, _ = run("The dress is too tight around my waist.", FakeLLM(out("LOOSE_AT_WAIST", 1.0)))
    assert result.status == "classified" and result.reason_code == "LOOSE_AT_WAIST"
    assert result.needs_confirm is True and result.confirm_note


def test_consistent_answer_is_accepted_without_a_question():
    result, _ = run("Maine medium size order kiya tha lekin bahut loose hai.", FakeLLM(out("SIZE_TOO_LARGE", 0.93)))
    assert result.needs_confirm is False and result.confirm_note is None


def test_secondary_reason_is_checked_too():
    result, _ = run("Sleeves chhoti hain aur size bada hai", FakeLLM(out("SIZE_TOO_LARGE", 0.9, secondary="SLEEVES_TOO_LONG")))
    assert result.needs_confirm is True


def test_confirm_flag_reaches_the_api(client, sarvam):
    sarvam.chat = [{**GOOD, "reason_code": "LOOSE_AT_WAIST", "confidence": 1.0}]
    body = analyse(client, "The dress is too tight around my waist.").json()
    assert body["status"] == "classified" and body["result"]["needs_confirm"] is True


# --- orders ------------------------------------------------------------------

def test_orders_need_login_and_hold_two_or_three_items_each(client):
    assert TestClient(main.app).get("/api/orders").status_code == 401
    body = client.get("/api/orders").json()
    assert [o["id"] for o in body["orders"]] == ["DH-24101", "DH-24102", "DH-24103"]
    for o in body["orders"]:
        assert 2 <= len(o["items"]) <= 3
        assert o["total"] == sum(i["price"] for i in o["items"])
        assert all(399 <= i["price"] <= 1499 for i in o["items"])      # the brief's price range


def test_every_item_ref_is_accepted_by_the_analyse_endpoint():
    for o in orders.ORDERS:
        for i in o["items"]:
            assert main._product_ref("sku", i["sku"]) == i["sku"]
            assert main._product_ref("vendor", i["vendor"]) == i["vendor"]


def test_sku_codes_are_unique():
    skus = [i["sku"] for o in orders.ORDERS for i in o["items"]]
    assert len(skus) == len(set(skus))


# --- the customer's own choice -----------------------------------------------

def choose(client, **data):
    return client.post("/api/returns/choose", data=data)


def test_choice_from_the_tiles_is_stored_for_the_digest(client):
    r = choose(client, reason_code="SIZE_TOO_SMALL", sku="DH-ALN-0540", vendor="Tiruppur V03")
    assert r.status_code == 200 and r.json()["status"] == "classified"
    row = store.get(r.json()["saved_id"])
    assert (row["reason_code"], row["route"], row["sku"], row["status"]) == ("SIZE_TOO_SMALL", "customer", "DH-ALN-0540", "classified")
    assert row["owner"] == "Neha (catalogue, size charts)"


def test_choice_corrects_the_models_row_in_place(client, sarvam):
    sarvam.chat = [{**GOOD, "reason_code": "LOOSE_AT_WAIST", "confidence": 1.0}]
    first = analyse(client, "The dress is too tight around my waist.").json()
    r = choose(client, reason_code="SIZE_TOO_SMALL", return_id=str(first["saved_id"]), sku="DH-ALN-0540")
    assert r.json()["saved_id"] == first["saved_id"]
    row = store.get(first["saved_id"])
    assert row["reason_code"] == "SIZE_TOO_SMALL" and row["route"] == "customer" and row["confidence"] is None
    assert client.get("/api/returns/stats").json()["total"] == 1       # corrected, not duplicated


def test_choice_settles_a_needs_review_row_and_leaves_the_queue(client, sarvam):
    sarvam.chat = [{**GOOD, "reason_code": "UNCLEAR_FREE_TEXT", "confidence": 0.9}]
    first = analyse(client, "I don't like it").json()
    assert client.get("/api/returns/review").json()["count"] == 1
    choose(client, reason_code="CHANGED_MY_MIND", return_id=str(first["saved_id"]))
    assert client.get("/api/returns/review").json()["count"] == 0


def test_something_else_goes_to_the_team_not_a_guess(client):
    r = choose(client, reason_code="UNCLEAR_FREE_TEXT", sku="DH-ALN-0540")
    assert r.json()["status"] == "needs_review"
    assert client.get("/api/returns/review").json()["count"] == 1


def test_choice_validates_input_and_needs_login(client):
    assert choose(client, reason_code="NOT_A_REASON").status_code == 422
    assert choose(client, reason_code="SIZE_TOO_SMALL", sku="bad<sku>").status_code == 422
    assert TestClient(main.app).post("/api/returns/choose", data={"reason_code": "SIZE_TOO_SMALL"}).status_code == 401


def test_menu_has_customer_friendly_names(client):
    cats = client.get("/api/returns/taxonomy").json()["categories"]
    labels = {c["code"]: c["customer_label"] for c in cats}
    assert labels["CUSTOMER"] == "I changed my mind" and labels["UNCLEAR"] == "Something else"
    assert all("no defect" not in v.lower() and "unclassifiable" not in v.lower() for v in labels.values())
