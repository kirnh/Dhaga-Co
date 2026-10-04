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
    """The customer's delivered orders (three demo orders; there is no orders feed in this MVP)."""
    return {"customer": orders.CUSTOMER, "orders": orders.ORDERS}


PENDING_MESSAGE = "We couldn't analyse this right now. Your return reason has been saved for retry."


@app.post("/api/returns/analyse", dependencies=[Depends(require_login)])
async def analyse_return(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    language_code: str = Form("unknown"),  # "unknown" = Sarvam auto-detects the language
    sku: str | None = Form(None),     # which product this return is about; the weekly digest groups by it
    vendor: str | None = Form(None),
):
    """Customer return reason as text OR a voice note -> structured reason.

    Voice is transcribed first; after that both inputs go through the same
    returns.classify_return() call.
    """
    headers()
    audio = await file.read() if file is not None and file.filename else b""
    text = (text or "").strip()
    if bool(audio) == bool(text):
        raise HTTPException(400, "Send either a typed reason or a voice note (one, not both).")

    sku, vendor = _product_ref("sku", sku), _product_ref("vendor", vendor)
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
        saved_id = _keep(lambda: store.save_pending(source, e.stage, costs, sku, vendor)) if source["text"] else None
        return JSONResponse(status_code=503, content={
            "status": "pending", "message": PENDING_MESSAGE, "failed_step": e.stage,
            "input": source, "costs": costs, "saved_id": saved_id,
        })
    for s in steps:
        s.pop("finish_reason", None)
    costs, meta = cost_summary(steps), returns.run_meta()
    saved_id = _keep(lambda: store.save_result(source, result.model_dump(), costs, meta, sku, vendor))
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
):
    """The customer picked the reason from the tiles. No model call. The choice is stored, so the
    weekly digest counts it, and it replaces the model's answer when return_id is given."""
    reason = taxonomy.REASONS.get(reason_code)
    if reason is None:
        raise HTTPException(422, f"'{reason_code}' is not a reason code from the list")
    sku, vendor = _product_ref("sku", sku), _product_ref("vendor", vendor)
    # "Something else" cannot be classified: it goes to the team's queue instead of being guessed.
    status = "needs_review" if taxonomy.is_unclear(reason_code) else "classified"
    saved_id = _keep(lambda: store.save_choice(reason.code, reason.owner, reason.category, status, sku, vendor,
                                                return_id, text.strip()[:returns.MAX_TEXT_CHARS]))
    return {"status": status, "reason_code": reason.code, "reason_label": reason.label,
            "category_label": reason.category_label, "owner": reason.owner, "saved_id": saved_id}


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
