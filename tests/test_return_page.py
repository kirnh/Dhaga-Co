"""The return page: raw input (with playback), the transcript, every tier, changing a return, and the orders link."""

import os

import pytest
from fastapi.testclient import TestClient

import main
import store
from test_api import AUDIO, GOOD, client, sarvam  # noqa: F401  (fixtures)

URL = "/api/returns/analyse"
ITEM = {"sku": "DH-KRT-0412", "vendor": "Jaipur V12", "order_id": "DH-24101"}


def voice(client, **extra):
    return client.post(URL, files=AUDIO, data={**ITEM, **extra})


def typed(client, text, **extra):
    return client.post(URL, data={"text": text, **ITEM, **extra})


# --- raw input and transcript ------------------------------------------------

def test_voice_note_is_kept_and_can_be_played_back(client, sarvam):
    body = voice(client).json()
    view = client.get(f"/api/returns/{body['saved_id']}").json()
    assert view["mode"] == "voice" and view["audio_url"] == f"/api/returns/{body['saved_id']}/audio"
    assert view["text"] == "Maine medium size order kiya tha lekin bahut loose hai."   # the transcript
    audio = client.get(view["audio_url"])
    assert audio.status_code == 200 and audio.content == b"\x00fake-audio" and audio.headers["content-type"] == "audio/mpeg"


def test_typed_return_has_no_audio(client, sarvam):
    body = typed(client, "bahut loose hai").json()
    view = client.get(f"/api/returns/{body['saved_id']}").json()
    assert view["mode"] == "text" and view["text"] == "bahut loose hai" and view["audio_url"] is None
    assert client.get(f"/api/returns/{body['saved_id']}/audio").status_code == 404


def test_the_view_shows_every_tier(client, sarvam):
    sarvam.chat = [{**GOOD, "secondary_reason_code": "STITCHING_CAME_APART", "details": ["size L ordered"]}]
    v = client.get(f"/api/returns/{typed(client, 'loose and stitching open').json()['saved_id']}").json()
    assert (v["category"], v["reason"]) == ("Size or fit", "Size too large")
    assert (v["secondary_category"], v["secondary"]) == ("Quality problem", "Stitching came apart")
    assert v["details"] == ["size L ordered"] and v["decided_by"] == "system" and v["unclear"] is False
    assert v["order_id"] == "DH-24101" and v["sku"] == "DH-KRT-0412"


def test_unclear_and_customer_choice_are_shown_as_such(client, sarvam):
    sarvam.chat = [{**GOOD, "reason_code": "UNCLEAR_FREE_TEXT"}]
    first = typed(client, "I don't like it").json()["saved_id"]
    assert client.get(f"/api/returns/{first}").json()["unclear"] is True
    client.post("/api/returns/choose", data={"reason_code": "CHANGED_MY_MIND", "return_id": str(first)})
    v = client.get(f"/api/returns/{first}").json()
    assert v["decided_by"] == "customer" and v["reason"] == "Changed my mind" and v["text"] == "I don't like it"


def test_team_resolution_wins_and_locks_changes(client, sarvam):
    sarvam.chat = [{**GOOD, "reason_code": "UNCLEAR_FREE_TEXT"}]
    rid = typed(client, "I don't like it").json()["saved_id"]
    client.post(f"/api/returns/review/{rid}/resolve", data={"reason_code": "SIZE_TOO_SMALL"})
    v = client.get(f"/api/returns/{rid}").json()
    assert (v["reason"], v["decided_by"], v["can_update"]) == ("Size too small", "team", False)
    assert typed(client, "actually loose", return_id=str(rid)).status_code == 409
    assert client.post("/api/returns/choose", data={"reason_code": "SIZE_TOO_LARGE", "return_id": str(rid)}).status_code == 409


def test_return_page_needs_login_and_unknown_id_is_404(client):
    anon = TestClient(main.app)
    assert anon.get("/api/returns/1").status_code == 401 and anon.get("/api/returns/1/audio").status_code == 401
    assert client.get("/api/returns/999").status_code == 404


# --- changing a return -------------------------------------------------------

def test_changing_a_return_rewrites_the_same_row_and_swaps_the_audio(client, sarvam):
    sarvam.chat = [GOOD, {**GOOD, "reason_code": "SIZE_TOO_SMALL"}]
    rid = voice(client).json()["saved_id"]
    old_file = store.get(rid)["audio_file"]
    assert os.path.isfile(os.path.join(store.audio_dir(), old_file))
    again = typed(client, "bahut tight hai", return_id=str(rid)).json()
    assert again["saved_id"] == rid
    row = store.get(rid)
    assert (row["reason_code"], row["input_mode"], row["text"], row["audio_file"]) == ("SIZE_TOO_SMALL", "text", "bahut tight hai", None)
    assert not os.path.exists(os.path.join(store.audio_dir(), old_file))   # the old recording is gone
    assert client.get("/api/returns/stats").json()["total"] == 1             # changed, not duplicated


def test_change_adds_up_the_cost_and_keeps_order_and_sku(client, sarvam):
    sarvam.chat = [GOOD, GOOD]
    rid = typed(client, "bahut loose hai").json()["saved_id"]
    once = store.get(rid)["cost_inr"]
    typed(client, "dheela hai", return_id=str(rid))
    row = store.get(rid)
    assert row["cost_inr"] == pytest.approx(once * 2) and (row["order_id"], row["sku"]) == ("DH-24101", "DH-KRT-0412")


def test_failed_change_keeps_the_earlier_return_as_it_was(client, sarvam):
    sarvam.chat = [GOOD, 503, 503]
    rid = typed(client, "bahut loose hai").json()["saved_id"]
    r = typed(client, "now it fails", return_id=str(rid))
    assert r.status_code == 503 and r.json()["saved_id"] is None
    assert store.get(rid)["text"] == "bahut loose hai" and client.get("/api/returns/stats").json()["total"] == 1


def test_changing_an_unknown_return_is_404(client, sarvam):
    assert typed(client, "bahut loose hai", return_id="999").status_code == 404


def test_oversized_recording_is_refused(client, sarvam, monkeypatch):
    monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 5)
    assert voice(client).status_code == 413


@pytest.mark.parametrize("ctype,filename,ext,mime", [
    ("audio/webm;codecs=opus", "voice.webm", "webm", "audio/webm"),
    ("audio/mp4", "voice.m4a", "m4a", "audio/mp4"),
    ("application/octet-stream", "note.ogg", "ogg", "audio/ogg"),
    ("text/html", "evil.html", "mp3", "audio/mpeg"),                 # never served as anything but audio
])
def test_only_known_audio_types_are_written(client, sarvam, ctype, filename, ext, mime):
    body = client.post(URL, files={"file": (filename, b"\x00fake", ctype)}, data=ITEM).json()
    row = store.get(body["saved_id"])
    assert row["audio_file"].endswith("." + ext) and row["audio_type"] == mime
    assert client.get(f"/api/returns/{body['saved_id']}/audio").headers["content-type"] == mime


# --- the orders page links to the return -------------------------------------

def test_orders_show_which_items_have_a_return(client, sarvam):
    def item(sku):
        return next(i for o in client.get("/api/orders").json()["orders"] for i in o["items"] if i["sku"] == sku)
    assert item("DH-KRT-0412")["return"] is None
    rid = typed(client, "bahut loose hai").json()["saved_id"]
    summary = item("DH-KRT-0412")["return"]
    assert summary == {"id": rid, "status": "classified", "reason": "Size too large", "unclear": False}
    assert item("DH-PLZ-0233")["return"] is None                    # other items are untouched


def test_orders_show_the_latest_state_after_a_change(client, sarvam):
    sarvam.chat = [GOOD, {**GOOD, "reason_code": "UNCLEAR_FREE_TEXT"}]
    rid = typed(client, "bahut loose hai").json()["saved_id"]
    typed(client, "meh", return_id=str(rid))
    got = next(i for i in client.get("/api/orders").json()["orders"][0]["items"] if i["sku"] == "DH-KRT-0412")["return"]
    assert got["unclear"] is True and got["id"] == rid


def test_order_id_is_validated(client, sarvam):
    assert client.post(URL, data={"text": "bahut loose hai", "order_id": "bad<id>"}).status_code == 422
