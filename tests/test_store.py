"""Storage and the team's Needs Review queue. Sarvam is faked as in test_api.py."""

import pytest
from fastapi.testclient import TestClient

import main
import store
from test_api import AUDIO, GOOD, URL, client, sarvam  # noqa: F401  (fixtures)

UNCLEAR = {"reason_code": "UNCLEAR_FREE_TEXT", "secondary_reason_code": None, "details": [],
           "confidence": 0.9, "explanation": "no reason"}


def analyse(client, text):
    return client.post(URL, data={"text": text})


def test_every_analysis_is_stored_and_the_id_is_returned(client, sarvam):
    body = analyse(client, "bahut loose hai").json()
    assert body["saved_id"] == 1
    row = store.get(1)
    assert row["status"] == "classified" and row["reason_code"] == "SIZE_TOO_LARGE"
    assert row["text"] == "bahut loose hai" and row["route"] == "first_pass"
    assert row["taxonomy_version"] and row["prompt_hash"] and row["cost_inr"] > 0


def test_needs_review_goes_to_the_open_queue_but_classified_does_not(client, sarvam):
    sarvam.chat = [GOOD, UNCLEAR]
    analyse(client, "bahut loose hai")
    analyse(client, "I don't like it")
    q = client.get("/api/returns/review").json()
    assert q["count"] == 1
    assert q["items"][0]["text"] == "I don't like it" and q["items"][0]["status"] == "needs_review"


def test_voice_return_stores_the_transcript_and_language(client, sarvam):
    client.post(URL, files=AUDIO)
    row = store.get(1)
    assert row["input_mode"] == "voice" and row["language"] == "hi-IN" and "loose" in row["text"]


def test_pending_return_is_kept_on_the_server(client, sarvam):
    sarvam.chat = [503, 503]
    r = analyse(client, "bahut loose hai")
    assert r.status_code == 503 and r.json()["saved_id"] == 1
    item = client.get("/api/returns/review").json()["items"][0]
    assert item["status"] == "pending" and item["text"] == "bahut loose hai" and item["failed_step"]


def test_nothing_to_keep_when_speech_to_text_fails(client, sarvam):
    sarvam.stt_status = 500
    r = client.post(URL, files=AUDIO)
    assert r.status_code == 503 and r.json()["saved_id"] is None
    assert store.stats()["total"] == 0


def test_resolve_settles_an_item_once(client, sarvam):
    sarvam.chat = [UNCLEAR]
    analyse(client, "kuch theek nahi")
    r = client.post("/api/returns/review/1/resolve", data={"reason_code": "SIZE_TOO_SMALL", "note": "called customer"})
    assert r.status_code == 200 and r.json()["resolved_code"] == "SIZE_TOO_SMALL"
    assert client.get("/api/returns/review").json()["count"] == 0
    done = client.get("/api/returns/review?state=resolved").json()
    assert done["count"] == 1 and done["items"][0]["resolved_note"] == "called customer"
    assert client.post("/api/returns/review/1/resolve", data={"reason_code": "SIZE_TOO_SMALL"}).status_code == 404


@pytest.mark.parametrize("code,status", [("MADE_UP_CODE", 422), ("UNCLEAR_FREE_TEXT", 422)])
def test_resolve_rejects_codes_not_in_the_list_or_unclear(client, sarvam, code, status):
    sarvam.chat = [UNCLEAR]
    analyse(client, "kuch theek nahi")
    assert client.post("/api/returns/review/1/resolve", data={"reason_code": code}).status_code == status
    assert client.get("/api/returns/review").json()["count"] == 1


def test_a_classified_return_cannot_be_resolved(client, sarvam):
    analyse(client, "bahut loose hai")
    assert client.post("/api/returns/review/1/resolve", data={"reason_code": "SIZE_TOO_SMALL"}).status_code == 404


def test_stats_share_classified_excludes_pending(client, sarvam):
    sarvam.chat = [GOOD, GOOD, UNCLEAR, 503, 503]
    for t in ("a loose", "b loose", "c unclear", "d outage"):
        analyse(client, t)
    s = client.get("/api/returns/stats").json()
    assert (s["total"], s["classified"], s["needs_review"], s["pending"]) == (4, 2, 1, 1)
    assert s["share_classified"] == pytest.approx(2 / 3, abs=1e-3)
    assert s["open_for_team"] == 2 and s["by_route"]["first_pass"] == 3
    assert s["by_reason"][0]["reason_code"] == "SIZE_TOO_LARGE" and s["by_reason"][0]["n"] == 2
    assert s["total_cost_inr"] > 0


def test_stats_on_an_empty_database(client):
    s = client.get("/api/returns/stats").json()
    assert s["total"] == 0 and s["share_classified"] is None and s["avg_cost_inr"] is None


def test_storage_failure_never_loses_the_customers_answer(client, sarvam, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(store, "save_result", broken)
    r = analyse(client, "bahut loose hai")
    assert r.status_code == 200 and r.json()["saved_id"] is None and r.json()["status"] == "classified"


def test_review_endpoints_need_login_and_validate_state(client):
    anon = TestClient(main.app)
    for method, path in [("get", "/api/returns/review"), ("get", "/api/returns/stats"),
                         ("post", "/api/returns/review/1/resolve")]:
        assert getattr(anon, method)(path).status_code == 401
    assert client.get("/api/returns/review?state=bogus").status_code == 400
