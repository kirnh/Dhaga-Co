"""Resetting the demo: clearing the returns on the demo orders so items can be returned again."""

import os

from fastapi.testclient import TestClient

import main
import store
from test_api import AUDIO, GOOD, client, sarvam  # noqa: F401  (fixtures)

ITEM = {"sku": "DH-KRT-0412", "vendor": "Jaipur V12", "order_id": "DH-24101"}


def returned_items(client):
    return [i["sku"] for o in client.get("/api/orders").json()["orders"] for i in o["items"] if i["return"]]


def test_reset_needs_login():
    assert TestClient(main.app).post("/api/orders/reset").status_code == 401


def test_reset_puts_every_item_back_to_return(client, sarvam):
    sarvam.chat = [GOOD, GOOD]
    client.post("/api/returns/analyse", data={"text": "bahut loose hai", **ITEM})
    client.post("/api/returns/analyse", files=AUDIO, data={"sku": "DH-PLZ-0233", "vendor": "Jaipur V12", "order_id": "DH-24101"})
    client.post("/api/returns/choose", data={"reason_code": "ZIP_NOT_WORKING", "sku": "DH-DUP-0087", "order_id": "DH-24101"})
    assert len(returned_items(client)) == 3

    assert client.post("/api/orders/reset").json() == {"cleared": 3}
    assert returned_items(client) == []
    assert client.post("/api/orders/reset").json() == {"cleared": 0}   # safe to press twice


def test_reset_deletes_the_voice_notes_too(client, sarvam):
    saved = client.post("/api/returns/analyse", files=AUDIO, data=ITEM).json()["saved_id"]
    assert len(os.listdir(store.audio_dir())) == 1
    client.post("/api/orders/reset")
    assert os.listdir(store.audio_dir()) == []
    assert client.get(f"/api/returns/{saved}").status_code == 404


def test_reset_also_clears_returns_attached_to_no_order(client, sarvam):
    """Rows from earlier builds have no order id: the orders page never lists them, but the team view does."""
    orphan = client.post("/api/returns/analyse", data={"text": "medium is too tight"}).json()["saved_id"]
    legacy = client.post("/api/returns/choose", data={"reason_code": "SLEEVES_TOO_SHORT", "sku": "DH-TOP-0129"}).json()["saved_id"]
    assert returned_items(client) == []                      # invisible on the customer screen
    assert client.post("/api/orders/reset").json() == {"cleared": 2}
    assert store.get(orphan) is None and store.get(legacy) is None
    assert all(q["items"] == [] for q in client.get("/api/team/board").json()["queues"])


def test_reset_leaves_other_rows_alone(client, sarvam):
    other = client.post("/api/returns/analyse", data={"text": "bahut loose hai", "sku": "X-1", "order_id": "OTHER-1"}).json()["saved_id"]
    seeded = store.save_result({"mode": "text", "text": "seed"}, main.returns.ReturnResult(
        status="classified", needs_review=False, primary_category="FIT", primary_category_label="Fit and size",
        owner="Neha", reason_code="SIZE_TOO_LARGE", reason_label="Size too large", confidence=0.9,
        route="first_pass").model_dump(), {"total_inr": 0}, {}, "DH-KRT-0412", "Jaipur V12",
        order_id=None, origin="demo")
    client.post("/api/orders/reset")
    for row_id in (other, seeded):
        assert store.get(row_id) is not None
