"""The weekly digest: counting, thresholds, who owns the fix. No model involved."""

from datetime import datetime, timedelta, timezone

import pytest

import digest
import store
import taxonomy
from test_api import GOOD, URL, client, sarvam  # noqa: F401  (fixtures)

NOW = datetime.now(timezone.utc)


def add(code, sku, vendor="Jaipur Textiles", days_ago=1, origin="live", text=None):
    r = taxonomy.REASONS[code]
    result = {"status": "classified", "reason_code": code, "primary_category": r.category, "owner": r.owner,
              "details": [], "confidence": 0.9, "route": "first_pass"}
    when = (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return store.save_result({"mode": "text", "text": text or f"{code} text", "detected_language": None},
                             result, {"total_inr": 0.08}, {}, sku, vendor, origin, when)


def background(n=40):
    """Ordinary returns spread over many SKUs, so each problem group has a normal share."""
    mix = ["SIZE_TOO_SMALL", "STITCHING_CAME_APART", "COLOUR_NOT_MATCHING", "WRONG_ITEM_SENT"]
    for i in range(n):
        add(mix[i % 4], f"SKU-{i % 10:02d}", "Tiruppur Knits")


def test_a_sku_with_an_unusual_cluster_is_flagged_with_owner_and_examples():
    background()
    for _ in range(12):
        add("SIZE_TOO_SMALL", "KRT-1042", text="L mangwaya tha, M jaisa lag raha hai")
    d = digest.build(7)
    top = d["findings"][0]
    assert (top["sku"], top["category"]) == ("KRT-1042", "FIT")
    assert top["owner"] == taxonomy.CATEGORIES["FIT"][1] and top["returns_in_group"] == 12
    assert top["top_reasons"][0] == {"reason": "Size too small", "n": 12}
    assert top["examples"] == ["L mangwaya tha, M jaisa lag raha hai"] * 3
    assert top["z"] >= digest.MIN_Z and top["action"]
    assert d["by_owner"][top["owner"]][0]["sku"] == "KRT-1042"


def test_ordinary_skus_are_not_flagged():
    background(80)
    assert digest.build(7)["findings"] == []


def test_below_the_minimum_count_is_not_flagged_however_skewed():
    background()
    for _ in range(4):
        add("SIZE_TOO_SMALL", "KRT-1042")
    assert digest.build(7)["findings"] == []
    assert digest.build(7, min_count=3, min_z=1)["findings"][0]["sku"] == "KRT-1042"


def test_returns_outside_the_window_are_ignored():
    background()
    for _ in range(12):
        add("SIZE_TOO_SMALL", "KRT-1042", days_ago=20)
    assert digest.build(7)["findings"] == []
    assert digest.build(30)["findings"][0]["sku"] == "KRT-1042"


def test_returns_without_a_sku_are_counted_but_cannot_be_flagged():
    for _ in range(15):
        add("SIZE_TOO_SMALL", None)
    d = digest.build(7)
    assert d["without_sku"] == 15 and d["with_sku"] == 0 and d["findings"] == []


def test_demo_rows_never_leak_into_live_numbers():
    background()
    for _ in range(12):
        add("SIZE_TOO_SMALL", "KRT-1042", origin="demo")
    assert digest.build(7)["findings"] == []
    assert digest.build(7, source="demo")["classified_returns"] == 12
    assert digest.build(7, source="all")["findings"][0]["sku"] == "KRT-1042"


def test_needs_review_and_pending_rows_are_not_in_the_digest(client, sarvam):
    sarvam.chat = [{"reason_code": "UNCLEAR_FREE_TEXT", "secondary_reason_code": None, "details": [],
                    "confidence": 0.9, "explanation": "x"}]
    client.post(URL, data={"text": "kuch theek nahi", "sku": "KRT-1042"})
    assert digest.build(7)["classified_returns"] == 0


def test_vendor_view_needs_twice_the_evidence():
    background()
    for _ in range(7):
        add("SIZE_TOO_SMALL", "KRT-1042", vendor="Jaipur Textiles")
        add("SIZE_TOO_SMALL", "KRT-1077", vendor="Jaipur Textiles")
    d = digest.build(7)
    assert d["thresholds"]["vendor_min_count"] == 10
    assert any(f["vendor"] == "Jaipur Textiles" and f["category"] == "FIT" for f in d["vendor_findings"])


def test_sku_and_vendor_travel_from_the_api_into_the_digest(client, sarvam):
    sarvam.chat = [GOOD] * 6
    for _ in range(6):
        r = client.post(URL, data={"text": "bahut loose hai", "sku": " KRT-1042 ", "vendor": "Jaipur Textiles"})
        assert r.status_code == 200
    row = store.get(1)
    assert (row["sku"], row["vendor"], row["source"]) == ("KRT-1042", "Jaipur Textiles", "live")
    d = client.get("/api/returns/digest?min_count=5&min_z=0").json()
    assert d["with_sku"] == 6 and d["classified_returns"] == 6


@pytest.mark.parametrize("field,value", [("sku", "x" * 65), ("sku", "<script>"), ("vendor", "a;drop table")])
def test_bad_sku_or_vendor_is_rejected_before_any_model_call(client, sarvam, field, value):
    r = client.post(URL, data={"text": "bahut loose hai", field: value})
    assert r.status_code == 422 and sarvam.requests == []


def test_digest_endpoint_validates_and_needs_login(client):
    from fastapi.testclient import TestClient
    import main
    assert TestClient(main.app).get("/api/returns/digest").status_code == 401
    for query in ("days=0", "days=400", "min_count=0", "min_z=-1", "source=everything"):
        assert client.get(f"/api/returns/digest?{query}").status_code == 400
    assert client.get("/api/returns/digest").json()["findings"] == []


def test_an_older_database_gains_the_new_columns(tmp_path, monkeypatch):
    import sqlite3
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE returns (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
        status TEXT NOT NULL, input_mode TEXT NOT NULL, text TEXT NOT NULL, language TEXT, reason_code TEXT,
        category TEXT, owner TEXT, secondary_code TEXT, details TEXT NOT NULL DEFAULT '[]', confidence REAL,
        explanation TEXT, review_hint TEXT, route TEXT, cost_inr REAL NOT NULL DEFAULT 0, taxonomy_version TEXT,
        prompt_hash TEXT, failed_step TEXT, resolved_at TEXT, resolved_code TEXT, resolved_note TEXT)""")
    conn.execute("INSERT INTO returns (created_at,status,input_mode,text) VALUES ('2026-10-01','needs_review','text','hi')")
    conn.commit(); conn.close()
    monkeypatch.setattr(store, "DB_PATH", str(old))
    row = store.review_queue()[0]
    assert row["text"] == "hi" and row["sku"] is None and row["source"] == "live"
