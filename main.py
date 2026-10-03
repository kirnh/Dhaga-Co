import io
import json
import os
import re
import time

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from mutagen import File as MutagenFile

load_dotenv()

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

SYSTEM_PROMPT = (
    "You extract structured data from a voice-note transcript according to the "
    "user's instructions. Respond with a single valid JSON object only. "
    "No markdown fences, no commentary."
)

app = FastAPI(title="Voice Note Parser")


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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/api/parse")
async def parse(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    language_code: str = Form("unknown"),
):
    h = headers()
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Empty file")

    steps = []
    async with httpx.AsyncClient(timeout=300) as client:
        # Step 1: speech-to-text
        t0 = time.monotonic()
        r = await client.post(
            f"{BASE_URL}/speech-to-text",
            headers=h,
            files={"file": (file.filename, audio, file.content_type or "audio/mpeg")},
            data={"model": STT_MODEL, "language_code": language_code, "with_timestamps": "true"},
        )
        stt_latency = time.monotonic() - t0
        if r.status_code != 200:
            raise HTTPException(r.status_code, f"Speech-to-text failed: {r.text}")
        stt = r.json()
        transcript = stt.get("transcript", "")

        secs = audio_seconds(audio)
        if secs is None:  # fall back to last timestamp
            ends = (stt.get("timestamps") or {}).get("end_time_seconds") or []
            secs = max(ends) if ends else 0.0
        stt_inr = secs / 3600 * STT_INR_PER_HOUR
        steps.append(
            cost_row("Speech-to-text", STT_MODEL, "audio sec", round(secs, 1),
                     f"₹{STT_INR_PER_HOUR}/hr", stt_inr, stt_latency)
        )

        # Step 2: LLM extraction
        t0 = time.monotonic()
        r = await client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers=h,
            json={
                "model": LLM_MODEL,
                "temperature": 0.2,
                "reasoning_effort": LLM_REASONING_EFFORT,
                "max_tokens": LLM_MAX_TOKENS,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Instructions:\n{prompt}\n\nTranscript:\n{transcript}"},
                ],
            },
        )
        llm_latency = time.monotonic() - t0
        if r.status_code != 200:
            raise HTTPException(r.status_code, f"LLM call failed: {r.text}")
        chat = r.json()
        choice = chat["choices"][0]
        content = choice["message"].get("content") or ""
        if choice.get("finish_reason") == "length" and not content:
            raise HTTPException(502, "LLM hit the token limit before producing output (reasoning used the budget). Raise LLM_MAX_TOKENS or lower LLM_REASONING_EFFORT.")
        usage = chat.get("usage") or {}
        tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        llm_inr = tin / 1e6 * LLM_INR_PER_M_INPUT + tout / 1e6 * LLM_INR_PER_M_OUTPUT
        steps.append(
            cost_row("LLM extraction", LLM_MODEL, "tokens", f"{tin} in / {tout} out",
                     f"₹{LLM_INR_PER_M_INPUT}/₹{LLM_INR_PER_M_OUTPUT} per 1M", llm_inr, llm_latency)
        )

    total_inr = sum(s["cost_inr"] for s in steps)
    return {
        "transcript": transcript,
        "detected_language": stt.get("language_code"),
        "result": parse_json(content),
        "raw_result": content,
        "costs": {
            "steps": steps,
            "total_inr": round(total_inr, 6),
            "total_usd": round(total_inr / INR_PER_USD, 6),
        },
    }
