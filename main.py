import io
import json
import os
import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import time

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from mutagen import File as MutagenFile

load_dotenv()  # before importing returns, which reads its settings from the environment

import digest  # noqa: E402
import orders  # noqa: E402
import returns  # noqa: E402
import store  # noqa: E402
import taxonomy  # noqa: E402

log = logging.getLogger("dhaga")

API_KEY = os.getenv("SARVAM_API_KEY")
BASE_URL = "https://api.sarvam.ai"
STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v4")
LLM_MODEL = os.getenv("SARVAM_LLM_MODEL", "sarvam-105b")

# Rates in INR, from https://www.sarvam.ai/api-pricing. Verify against your plan.
# Override via .env if pricing changes.
STT_INR_PER_HOUR = float(os.getenv("STT_INR_PER_HOUR", "30.00"))
LLM_INR_PER_M_INPUT = float(os.getenv("LLM_INR_PER_M_INPUT", "29.28"))
LLM_INR_PER_M_OUTPUT = float(os.getenv("LLM_INR_PER_M_OUTPUT", "73.20"))
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")  # reasoning tokens are billed as output
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192"))
INR_PER_USD = float(os.getenv("INR_PER_USD", "88.0"))
RETURN_TIMEOUT_S = float(os.getenv("RETURN_TIMEOUT_S", "30"))  # per Sarvam call on the returns screen

SYSTEM_PROMPT = (
    "You extract structured data from a voice-note transcript according to the "
    "user's instructions. Respond with a single valid JSON object only. "
    "No markdown fences, no commentary."
)

# Shared team password. Unset = everything except /health is locked.
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
COOKIE = "dhaga_session"


def session_value() -> str:
    # Stateless: HMAC keyed by the password, so changing the password logs everyone out.
    return hmac.new(APP_PASSWORD.encode(), b"dhaga-session", hashlib.sha256).hexdigest()


def authed(request: Request) -> bool:
    got = request.cookies.get(COOKIE, "")
    return bool(APP_PASSWORD) and secrets.compare_digest(got.encode(), session_value().encode())


def require_login(request: Request):
    if not authed(request):
        raise HTTPException(401, "Not signed in")


app = FastAPI(title="Dhaga & Co. Returns")


def headers() -> dict:
    if not API_KEY:
        raise HTTPException(500, "SARVAM_API_KEY is not set in .env")
    return {"api-subscription-key": API_KEY}


def audio_seconds(data: bytes) -> float | None:
    try:
        f = MutagenFile(io.BytesIO(data))
        return float(f.info.length) if f and f.info else None
    except Exception:
        return None


def cost_row(name, model, unit_label, units, rate_label, inr, latency):
    return {
        "step": name,
        "model": model,
        "usage": f"{units} {unit_label}",
        "rate": rate_label,
        "cost_inr": round(inr, 6),
        "cost_usd": round(inr / INR_PER_USD, 6),
        "latency_s": round(latency, 2),
    }


def parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


class UpstreamError(Exception):
    """A Sarvam call failed (bad status, timeout or no connection)."""

    def __init__(self, stage: str, status: int | None, detail: str):
        super().__init__(f"{stage} failed: {detail}")
        self.stage, self.status, self.detail = stage, status, detail


def http_client(timeout: float = 300) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


async def _post(client: httpx.AsyncClient, stage: str, path: str, **kwargs) -> httpx.Response:
    try:
        r = await client.post(f"{BASE_URL}{path}", headers=headers(), **kwargs)
    except httpx.HTTPError as e:  # timeout, DNS, connection reset...
        raise UpstreamError(stage, None, type(e).__name__)
    if r.status_code != 200:
        raise UpstreamError(stage, r.status_code, r.text)
    return r


async def transcribe(client, audio: bytes, filename: str, content_type: str | None,
                     language_code: str = "unknown") -> tuple[dict, dict]:
    """Sarvam speech-to-text. Returns (response JSON, cost row)."""
    t0 = time.monotonic()
    r = await _post(
        client, "Speech-to-text", "/speech-to-text",
        files={"file": (filename, audio, content_type or "audio/mpeg")},
        data={"model": STT_MODEL, "language_code": language_code, "with_timestamps": "true"},
    )
    latency = time.monotonic() - t0
    stt = r.json()
    secs = audio_seconds(audio)
    if secs is None:  # fall back to last timestamp
        ends = (stt.get("timestamps") or {}).get("end_time_seconds") or []
        secs = max(ends) if ends else 0.0
    row = cost_row("Speech-to-text", STT_MODEL, "audio sec", round(secs, 1),
                   f"₹{STT_INR_PER_HOUR}/hr", secs / 3600 * STT_INR_PER_HOUR, latency)
    return stt, row


_structured_output_ok = True  # switched off if Sarvam rejects response_format


async def chat(client, messages: list[dict], *, step: str, model: str, temperature: float,
               reasoning_effort: str | None, max_tokens: int,
               response_format: dict | None = None) -> tuple[str, dict]:
    """Sarvam chat completion. Returns (reply text, cost row)."""
    global _structured_output_ok
    body = {"model": model, "temperature": temperature, "reasoning_effort": reasoning_effort,
            "max_tokens": max_tokens, "messages": messages}
    if response_format and _structured_output_ok:
        body["response_format"] = response_format
    t0 = time.monotonic()
    try:
        r = await _post(client, step, "/v1/chat/completions", json=body)
    except UpstreamError as e:
        # If the schema itself is what Sarvam rejected, carry on without it:
        # our own validation still checks every reply.
        if e.status in (400, 422) and "response_format" in body:
            _structured_output_ok = False
            del body["response_format"]
            r = await _post(client, step, "/v1/chat/completions", json=body)
        else:
            raise
    latency = time.monotonic() - t0
    data = r.json()
    choice = data["choices"][0]
    content = choice["message"].get("content") or ""
    usage = data.get("usage") or {}
    tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    inr = tin / 1e6 * LLM_INR_PER_M_INPUT + tout / 1e6 * LLM_INR_PER_M_OUTPUT
    row = cost_row(step, model, "tokens", f"{tin} in / {tout} out",
                   f"₹{LLM_INR_PER_M_INPUT}/₹{LLM_INR_PER_M_OUTPUT} per 1M", inr, latency)
    row["finish_reason"] = choice.get("finish_reason")
    return content, row


def cost_summary(steps: list[dict]) -> dict:
    total_inr = sum(s["cost_inr"] for s in steps)
    return {"steps": steps, "total_inr": round(total_inr, 6), "total_usd": round(total_inr / INR_PER_USD, 6)}


def returns_llm(client):
    """The Sarvam-backed model call handed to returns.classify_return (temperature 0)."""
    async def llm(messages, **call):
        return await chat(client, messages, temperature=0, **call)
    return llm


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index(request: Request):
    return FileResponse("static/index.html" if authed(request) else "static/login.html")


@app.get("/team")
def team_page(request: Request):
    """The Dhaga team's view: which department each return was routed to, and the Needs Review queue."""
    return FileResponse("static/team.html" if authed(request) else "static/login.html")


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if not APP_PASSWORD:
        raise HTTPException(503, "APP_PASSWORD is not configured")
    if not secrets.compare_digest(password.encode(), APP_PASSWORD.encode()):
        await asyncio.sleep(1)  # slow down guessing
        return JSONResponse({"detail": "Wrong password"}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        COOKIE, session_value(), max_age=30 * 24 * 3600, httponly=True, samesite="lax",
        secure=request.headers.get("x-forwarded-proto") == "https",
    )
    return resp


@app.post("/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


@app.post("/api/parse", dependencies=[Depends(require_login)])
async def parse(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    language_code: str = Form("unknown"),
):
    headers()  # 500 early if the key is missing
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Empty file")

    try:
        async with http_client() as client:
            stt, stt_row = await transcribe(client, audio, file.filename, file.content_type, language_code)
            transcript = stt.get("transcript", "")
            content, llm_row = await chat(
                client,
                [{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user", "content": f"Instructions:\n{prompt}\n\nTranscript:\n{transcript}"}],
                step="LLM extraction", model=LLM_MODEL, temperature=0.2,
                reasoning_effort=LLM_REASONING_EFFORT, max_tokens=LLM_MAX_TOKENS,
            )
    except UpstreamError as e:
        raise HTTPException(e.status or 502, str(e))
    if llm_row.pop("finish_reason") == "length" and not content:
        raise HTTPException(502, "LLM hit the token limit before producing output (reasoning used the budget). Raise LLM_MAX_TOKENS or lower LLM_REASONING_EFFORT.")

    return {
        "transcript": transcript,
        "detected_language": stt.get("language_code"),
        "result": parse_json(content),
        "raw_result": content,
        "costs": cost_summary([stt_row, llm_row]),
    }


@app.get("/api/returns/taxonomy", dependencies=[Depends(require_login)])
def returns_taxonomy():
    """First-level categories and the reasons under each, for the two dropdowns."""
    return taxonomy.as_menu()


@app.get("/api/orders", dependencies=[Depends(require_login)])
def list_orders():
    """The customer's delivered orders (three demo orders; there is no orders feed in this MVP).
    Each item says whether a return was requested for it, so the page can link to that return."""
    try:
        requested = store.latest_by_item()
    except Exception:
        log.exception("could not read the returns for the orders page")
        requested = {}

    def summary(order_id, sku):
        row = requested.get((order_id, sku))
        if row is None:
            return None
        v = _view(row)
        return {"id": v["id"], "status": v["status"], "reason": v["reason"], "unclear": v["unclear"]}

    return {"customer": orders.CUSTOMER, "orders": [
        {**o, "items": [{**i, "return": summary(o["id"], i["sku"])} for i in o["items"]]} for o in orders.ORDERS]}


@app.post("/api/orders/reset", dependencies=[Depends(require_login)])
def reset_orders():
    """Demo helper: clear the returns filed against the demo orders, so every item shows "Return"
    again. Deletes those rows and their voice notes for good; they also leave the review queue
    and the digest. Nothing else in the database is touched."""
    cleared, files = store.clear_orders([o["id"] for o in orders.ORDERS])
    for name in files:
        _drop_audio(name)
    return {"cleared": cleared}


PENDING_MESSAGE = "We couldn't analyse this right now. Your return reason has been saved for retry."


@app.post("/api/returns/analyse", dependencies=[Depends(require_login)])
async def analyse_return(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    language_code: str = Form("unknown"),  # "unknown" = Sarvam auto-detects the language
    sku: str | None = Form(None),     # which product this return is about; the weekly digest groups by it
    vendor: str | None = Form(None),
    order_id: str | None = Form(None),
    return_id: int | None = Form(None),  # the customer is changing this earlier return: it is rewritten in place
):
    """Customer return reason as text OR a voice note -> structured reason.

    Voice is transcribed first; after that both inputs go through the same
    returns.classify_return() call. A voice note is kept so the customer can play it back.
    """
    headers()
    audio = await file.read() if file is not None and file.filename else b""
    text = (text or "").strip()
    if bool(audio) == bool(text):
        raise HTTPException(400, "Send either a typed reason or a voice note (one, not both).")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, f"That recording is too big. Please keep it under {MAX_AUDIO_BYTES // 1_000_000} MB.")

    sku, vendor = _product_ref("sku", sku), _product_ref("vendor", vendor)
    order_id = _product_ref("order_id", order_id)
    previous = _changeable(return_id)
    steps: list[dict] = []
    source = {"mode": "voice" if audio else "text", "text": text, "detected_language": None}
    try:
        async with http_client(RETURN_TIMEOUT_S) as client:
            if audio:
                stt, row = await transcribe(client, audio, file.filename, file.content_type, language_code)
                steps.append(row)
                source["text"] = (stt.get("transcript") or "").strip()
                source["detected_language"] = stt.get("language_code")
                if not source["text"]:
                    raise HTTPException(422, "We couldn't hear any speech in that recording. Please try again or type your reason.")
            result, llm_steps = await returns.classify_return(source["text"], returns_llm(client))
            steps += llm_steps
    except UpstreamError as e:
        # Fail visibly, never as a 401 (the page treats 401 as "signed out").
        # Whatever we already have (typed text or transcript) goes back so nothing is lost,
        # and is also kept on the server so the team can settle it.
        costs = cost_summary(steps)
        # (a failed change leaves the earlier return as it was, rather than adding a second row)
        saved_id = (_keep(lambda: store.save_pending(source, e.stage, costs, sku, vendor, order_id))
                    if source["text"] and previous is None else None)
        return JSONResponse(status_code=503, content={
            "status": "pending", "message": PENDING_MESSAGE, "failed_step": e.stage,
            "input": source, "costs": costs, "saved_id": saved_id,
        })
    for s in steps:
        s.pop("finish_reason", None)
    costs, meta = cost_summary(steps), returns.run_meta()
    saved_id = _keep(lambda: store.save_result(source, result.model_dump(), costs, meta, sku, vendor,
                                                order_id=order_id, replace_id=return_id))
    if previous is not None:
        _drop_audio(previous.get("audio_file"))   # the new input replaces the old one
    if audio and saved_id:
        _keep(lambda: _store_audio(saved_id, audio, file.content_type, file.filename))
    return {
        "status": result.status,
        "input": source,
        "result": result.model_dump(),
        "costs": costs,
        "meta": meta,
        "saved_id": saved_id,  # None means the answer is shown but could not be stored
    }


@app.post("/api/returns/choose", dependencies=[Depends(require_login)])
def choose_reason(
    reason_code: str = Form(...),
    sku: str | None = Form(None),
    vendor: str | None = Form(None),
    return_id: int | None = Form(None),  # the earlier saved row to correct, if there was one
    text: str = Form(""),
    order_id: str | None = Form(None),
):
    """The customer picked the reason from the tiles. No model call. The choice is stored, so the
    weekly digest counts it, and it replaces the model's answer when return_id is given."""
    reason = taxonomy.REASONS.get(reason_code)
    if reason is None:
        raise HTTPException(422, f"'{reason_code}' is not a reason code from the list")
    sku, vendor = _product_ref("sku", sku), _product_ref("vendor", vendor)
    order_id = _product_ref("order_id", order_id)
    _changeable(return_id)
    # "Something else" cannot be classified: it goes to the team's queue instead of being guessed.
    status = "needs_review" if taxonomy.is_unclear(reason_code) else "classified"
    saved_id = _keep(lambda: store.save_choice(reason.code, reason.owner, reason.category, status, sku, vendor,
                                                return_id, text.strip()[:returns.MAX_TEXT_CHARS], order_id))
    return {"status": status, "reason_code": reason.code, "reason_label": reason.label,
            "category_label": reason.category_label, "owner": reason.owner, "saved_id": saved_id}


MAX_AUDIO_BYTES = 10_000_000
AUDIO_EXT = {"audio/webm": "webm", "video/webm": "webm", "audio/ogg": "ogg", "audio/opus": "ogg", "audio/mp4": "m4a",
             "audio/x-m4a": "m4a", "audio/m4a": "m4a", "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav",
             "audio/x-wav": "wav", "audio/wave": "wav", "audio/flac": "flac", "audio/aac": "aac"}
AUDIO_MIME = {"webm": "audio/webm", "ogg": "audio/ogg", "m4a": "audio/mp4", "mp3": "audio/mpeg", "wav": "audio/wav",
              "flac": "audio/flac", "aac": "audio/aac"}


def _changeable(return_id: int | None) -> dict | None:
    """The earlier return a customer wants to change, if it exists and the team has not settled it."""
    if return_id is None:
        return None
    row = store.get(return_id)
    if row is None:
        raise HTTPException(404, "We couldn't find that return.")
    if row.get("resolved_at"):
        raise HTTPException(409, "Our team has already settled this return, so it can't be changed here.")
    return row


def _store_audio(row_id: int, audio: bytes, content_type: str | None, filename: str | None) -> None:
    """Keep the voice note beside the database. Only a fixed set of audio types is ever written or served."""
    ext = AUDIO_EXT.get((content_type or "").split(";")[0].strip().lower())
    if ext is None:
        suffix = os.path.splitext(filename or "")[1].lstrip(".").lower()
        ext = suffix if suffix in AUDIO_MIME else "mp3"
    name = f"{row_id}-{secrets.token_hex(4)}.{ext}"
    folder = store.audio_dir()
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "wb") as f:
        f.write(audio)
    store.set_audio(row_id, name, AUDIO_MIME[ext])


def _drop_audio(name: str | None) -> None:
    if name:
        try:
            os.remove(os.path.join(store.audio_dir(), os.path.basename(name)))
        except OSError:
            pass


def _view(row: dict) -> dict:
    """One return as the customer sees it: what they gave us, how we read it, who decided."""
    code = row.get("resolved_code") or row.get("reason_code")
    reason = taxonomy.REASONS.get(code) if code else None
    second = taxonomy.REASONS.get(row.get("secondary_code")) if row.get("secondary_code") and not row.get("resolved_code") else None
    decided = "team" if row.get("resolved_code") else "customer" if row.get("route") == "customer" else "system"
    return {
        "id": row["id"], "status": row["status"], "created_at": row["created_at"],
        "mode": row["input_mode"], "text": row["text"], "language": row.get("language"),
        "audio_url": f"/api/returns/{row['id']}/audio" if row.get("audio_file") else None,
        "category": taxonomy.CUSTOMER_LABELS.get(reason.category) if reason else None,
        "reason": reason.label if reason else None,
        "secondary_category": taxonomy.CUSTOMER_LABELS.get(second.category) if second else None,
        "secondary": second.label if second else None,
        "details": row.get("details") or [],
        "unclear": reason is None or taxonomy.is_unclear(code),
        "decided_by": decided,
        "can_update": not row.get("resolved_at"),
        "order_id": row.get("order_id"), "sku": row.get("sku"), "vendor": row.get("vendor"),
        # for the team panel (?staff)
        "owner": row.get("owner"), "route": row.get("route"), "confidence": row.get("confidence"),
        "cost_inr": row.get("cost_inr"), "taxonomy_version": row.get("taxonomy_version"),
    }


@app.get("/api/returns/{return_id:int}", dependencies=[Depends(require_login)])
def returns_one(return_id: int):
    """One return: the raw input, the transcript, and every tier of the classification."""
    row = store.get(return_id)
    if row is None:
        raise HTTPException(404, "No such return.")
    return _view(row)


@app.get("/api/returns/{return_id:int}/audio", dependencies=[Depends(require_login)])
def returns_audio(return_id: int):
    """The customer's own voice note, for playback."""
    row = store.get(return_id)
    name = row.get("audio_file") if row else None
    path = os.path.join(store.audio_dir(), os.path.basename(name)) if name else None
    if not path or not os.path.isfile(path):
        raise HTTPException(404, "No recording for this return.")
    return FileResponse(path, media_type=row.get("audio_type") or "audio/mpeg")


PRODUCT_REF = re.compile(r"^[\w .,/&()'-]{1,64}$")


def _product_ref(field: str, value: str | None) -> str | None:
    """A SKU or vendor name from the caller: optional, short, plain text."""
    value = (value or "").strip()
    if not value:
        return None
    if not PRODUCT_REF.match(value):
        raise HTTPException(422, f"{field} must be 1-64 plain characters (letters, digits, space and . , / & ( ) ' -).")
    return value


def _keep(save):
    """Storing is secondary: if the database fails the customer still gets their answer."""
    try:
        return save()
    except Exception:
        log.exception("could not store the return")
        return None


@app.get("/api/returns/review", dependencies=[Depends(require_login)])
def returns_review(state: str = "open"):
    """The team's queue: returns the system would not guess (Needs Review) or could not read yet (pending)."""
    if state not in ("open", "resolved"):
        raise HTTPException(400, "state must be 'open' or 'resolved'")
    items = store.review_queue(state)
    return {"state": state, "count": len(items), "items": items}


@app.post("/api/returns/review/{return_id}/resolve", dependencies=[Depends(require_login)])
def returns_resolve(return_id: int, reason_code: str = Form(...), note: str = Form("")):
    """The team picks the right reason for a queued return. The code must be one from the list."""
    if reason_code not in taxonomy.REASONS:
        raise HTTPException(422, f"'{reason_code}' is not a reason code from the list")
    if taxonomy.is_unclear(reason_code):
        raise HTTPException(422, "Pick a specific reason. An unclear reason cannot settle an item.")
    row = store.resolve(return_id, reason_code, note)
    if row is None:
        raise HTTPException(404, "No open item with that id (it may already be settled).")
    return row


@app.get("/api/team/board", dependencies=[Depends(require_login)])
def team_board():
    """Every recent return, placed in the queue of the team that owns its reason.

    Routing is the lookup in taxonomy.py (reason -> group -> owner); no model is asked.
    A return with a second problem also appears, marked "also", in that problem's queue.
    Unclear and unread returns sit in the Needs Review queue until a person settles them.
    """
    names = {(o["id"], i["sku"]): i["name"] for o in orders.ORDERS for i in o["items"]}
    queues = {cat: {"category": cat, "department": label, "owner": owner,
                    "needs_review": cat == taxonomy.UNCLEAR_CATEGORY, "items": []}
              for cat, (label, owner, _items) in taxonomy.CATEGORIES.items()}

    def card(row, reason, role, other=None):
        return {
            "id": row["id"], "created_at": row["created_at"], "role": role,   # main | also | review
            "item": names.get((row.get("order_id"), row.get("sku"))), "order_id": row.get("order_id"),
            "sku": row.get("sku"), "vendor": row.get("vendor"),
            "reason": reason.label if reason else None,
            "other_reason": other.label if other else None, "other_owner": other.owner if other else None,
            "text": row["text"], "mode": row["input_mode"], "status": row["status"],
            "review_hint": (taxonomy.REASONS[row["review_hint"]].label
                            if row.get("review_hint") in taxonomy.REASONS else None),
            "failed_step": row.get("failed_step"),
            "decided_by": "team" if row.get("resolved_code") else "customer" if row.get("route") == "customer" else "system",
        }

    for row in store.recent():
        code = row.get("resolved_code") or row.get("reason_code")
        reason = taxonomy.REASONS.get(code) if code else None
        if reason is None or taxonomy.is_unclear(code):      # pending, or the system would not guess
            queues[taxonomy.UNCLEAR_CATEGORY]["items"].append(card(row, reason, "review"))
            continue
        second = None if row.get("resolved_code") else taxonomy.REASONS.get(row.get("secondary_code") or "")
        queues[reason.category]["items"].append(card(row, reason, "main", second))
        if second and second.category != reason.category:
            queues[second.category]["items"].append(card(row, second, "also", reason))
    ordered = sorted(queues.values(), key=lambda q: not q["needs_review"])   # the human queue first
    return {"queues": ordered}


@app.get("/api/returns/stats", dependencies=[Depends(require_login)])
def returns_stats():
    """Share classified, route mix and cost so far. The numbers behind the success metric."""
    return store.stats()



@app.get("/api/returns/digest", dependencies=[Depends(require_login)])
def returns_digest(days: int = 7, min_count: int | None = None, min_z: float | None = None,
                   source: str = "live"):
    """Weekly digest: SKUs and vendors with an unusually common problem, grouped by who fixes it.

    source is 'live' (real returns), 'demo' (synthetic rows from eval/seed_demo.py) or 'all'.
    """
    if not 1 <= days <= 365:
        raise HTTPException(400, "days must be between 1 and 365")
    if min_count is not None and min_count < 1:
        raise HTTPException(400, "min_count must be at least 1")
    if min_z is not None and min_z < 0:
        raise HTTPException(400, "min_z must not be negative")
    if source not in ("live", "demo", "all"):
        raise HTTPException(400, "source must be live, demo or all")
    return digest.build(days, min_count, min_z, source)
