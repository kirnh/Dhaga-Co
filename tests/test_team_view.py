"""The team view: each return lands in the queue of the team that owns its reason."""

from fastapi.testclient import TestClient

import main
from test_api import GOOD, client, sarvam  # noqa: F401  (fixtures)

ITEM = {"sku": "DH-KRT-0412", "vendor": "Jaipur V12", "order_id": "DH-24101"}


def board(client):
    return {q["category"]: q for q in client.get("/api/team/board").json()["queues"]}


def test_team_page_and_board_need_login():
    anon = TestClient(main.app)
    assert anon.get("/api/team/board").status_code == 401
    assert "Team view" not in anon.get("/team").text      # the login page is served instead


def test_team_page_is_served_after_login(client):
    assert "Team view" in client.get("/team").text


def test_every_department_has_a_queue_even_when_empty(client):
    b = board(client)
    assert len(b) == 7 and all(q["items"] == [] for q in b.values())
    assert b["FIT"]["owner"].startswith("Neha") and b["DELIVERY"]["owner"].startswith("Faizan")
    assert client.get("/api/team/board").json()["queues"][0]["needs_review"] is True   # human queue first


def test_a_classified_return_goes_to_its_owner(client, sarvam):
    client.post("/api/returns/analyse", data={"text": "bahut loose hai", **ITEM})
    b = board(client)
    [card] = b["FIT"]["items"]
    assert (card["reason"], card["role"], card["item"]) == ("Size too large", "main", "Cotton kurti, mustard")
    assert card["text"] == "bahut loose hai" and card["decided_by"] == "system"
    assert all(q["items"] == [] for cat, q in b.items() if cat != "FIT")


def test_two_problems_appear_in_both_owners_queues(client, sarvam):
    sarvam.chat = [{**GOOD, "secondary_reason_code": "STITCHING_CAME_APART"}]
    client.post("/api/returns/analyse", data={"text": "loose hai aur silai khuli hai", **ITEM})
    b = board(client)
    assert b["FIT"]["items"][0]["role"] == "main" and b["FIT"]["items"][0]["other_reason"] == "Stitching came apart"
    also = b["QUALITY"]["items"][0]
    assert also["role"] == "also" and also["reason"] == "Stitching came apart" and also["other_owner"].startswith("Neha")


def test_unclear_waits_in_needs_review_then_moves_when_settled(client, sarvam):
    sarvam.chat = [{**GOOD, "reason_code": "UNCLEAR_FREE_TEXT", "details": []}]
    saved = client.post("/api/returns/analyse", data={"text": "mera mood kharab hai", **ITEM}).json()["saved_id"]
    b = board(client)
    assert [c["id"] for c in b["UNCLEAR"]["items"]] == [saved] and b["CUSTOMER"]["items"] == []

    client.post(f"/api/returns/review/{saved}/resolve", data={"reason_code": "RECIPIENT_DIDNT_LIKE"})
    b = board(client)
    assert b["UNCLEAR"]["items"] == []
    [card] = b["CUSTOMER"]["items"]
    assert card["reason"] == "Recipient didn't like" and card["decided_by"] == "team"


def test_a_customer_pick_is_marked_as_such(client):
    client.post("/api/returns/choose", data={"reason_code": "DELIVERED_TOO_LATE", **ITEM})
    assert board(client)["DELIVERY"]["items"][0]["decided_by"] == "customer"


def test_a_failed_analysis_is_visible_to_the_team(client, sarvam):
    sarvam.chat = [500]
    client.post("/api/returns/analyse", data={"text": "zip kharab hai", **ITEM})
    [card] = board(client)["UNCLEAR"]["items"]
    assert card["status"] == "pending" and card["text"] == "zip kharab hai" and card["failed_step"] == "Classify"
