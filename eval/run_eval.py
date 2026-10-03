"""Run the labelled samples through the real pipeline and report how it did.

    uv run python eval/run_eval.py --baseline         # keyword baseline, no API key, free
    uv run python eval/run_eval.py --limit 5          # quick live check (needs SARVAM_API_KEY in .env)
    uv run python eval/run_eval.py                    # full live run, about 120 rows
    uv run python eval/run_eval.py --no-evaluator     # ablation: first pass only
    uv run python eval/run_eval.py --second-opinion   # two independent fast readings, compared by code
    uv run python eval/run_eval.py --audio-dir ~/Downloads/Dhaga_ReturnReasons_Audio   # voice path

Writes eval/results-<name>.csv and eval/summary-<name>.txt. Send both back.
"""

import argparse
import asyncio
import csv
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

import returns  # noqa: E402
from taxonomy import EXAMPLES, REASONS, UNCLEAR_CODE, is_unclear  # noqa: E402

BY_REF = {r.ref: r.code for r in REASONS.values() if r.ref is not None}
SMALL = {"SIZE_TOO_SMALL", "LENGTH_TOO_SHORT", "TIGHT_AT_CHEST", "SLEEVES_TOO_SHORT"}
LARGE = {"SIZE_TOO_LARGE", "LENGTH_TOO_LONG", "LOOSE_AT_WAIST", "SLEEVES_TOO_LONG"}

# Keyword baseline (judge question: "why pay for a model at all?"). First match wins.
# Evaluation-only; the app never uses it. Written after reading the samples, so it is flattered.
KEYWORDS = [
    ("BLEEDS_WHEN_WASHED", ["wash", "dhoy", "dhoi", "bleed", "rang nikal", "colour nikal", "rang beh", "dye"]),
    ("FABRIC_IS_TRANSPARENT", ["transparent", "see-through", "paardarshi", "aar-paar", "jhina", "lining"]),
    ("STITCHING_CAME_APART", ["stitching", "silai", "seam", "udhad"]),
    ("FABRIC_FEELS_CHEAP", ["fabric", "kapda", "material", "polyester", "synthetic", "cotton"]),
    ("SIZE_CHART_MISLEADING", ["size chart", "chart"]),
    ("KIDS_SIZE_MISMATCH", ["years", "saal", "age "]),
    ("FIT_UNLIKE_PHOTOS", ["photo", "tasveer", "website pe", "listing mein", "model"]),
    ("SLEEVES_TOO_LONG", ["sleeves bahut lambi", "sleeves too long", "baahein bahut lambi", "aasteen bahut lambi", "sleeves ungliyon", "wrist se teen"]),
    ("SLEEVES_TOO_SHORT", ["sleeve", "baahein", "aasteen"]),
    ("TIGHT_AT_CHEST", ["chest", "bust", "chhaati"]),
    ("LOOSE_AT_WAIST", ["waist", "kamar"]),
    ("LENGTH_TOO_LONG", ["lambi", "lamba", "lambai", "too long", "length bahut zyada"]),
    ("LENGTH_TOO_SHORT", ["length", "short", "chhoti hai", "chhota hai"]),
    ("SIZE_TOO_LARGE", ["loose", "bada", "badi", "dheel", "large"]),
    ("SIZE_TOO_SMALL", ["tight", "chhot", "chota", "small", "tang"]),
    ("COLOUR_NOT_MATCHING", ["colour", "color", "rang"]),
    ("WRONG_ITEM_SENT", ["galat", "wrong", "ki jagah"]),
    ("TORN_ON_ARRIVAL", ["phat", "damage", "torn"]),
    ("STAIN_ON_GARMENT", ["daag", "stain"]),
    ("DELIVERED_TOO_LATE", ["late", "der se"]),
    ("OCCASION_ALREADY_PASSED", ["shaadi", "function"]),
]
assert all(code in REASONS for code, _ in KEYWORDS)


def keyword_baseline(text: str) -> dict:
    low = text.lower()
    for code, words in KEYWORDS:
        if any(w in low for w in words):
            return {"status": "classified", "reason_code": code, "secondary": "", "confidence": "",
                    "route": "keywords", "review_hint": ""}
    return {"status": "needs_review", "reason_code": UNCLEAR_CODE, "secondary": "", "confidence": "",
            "route": "keywords", "review_hint": ""}


def load_rows(script: str) -> list[dict]:
    rows = []
    with open(HERE / "labelled_samples.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"id": r["id"], "set": "labelled", "expected": BY_REF[int(r["reason_ref"])],
                         "expected_secondary": "", "label_spoken": r["label_spoken"],
                         "text": r["devanagari"] if script == "devanagari" else r["roman_hinglish"],
                         "audio_file": r["audio_file"]})
    with open(HERE / "hard_cases.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"id": r["id"], "set": "hard", "expected": r["expected"],
                         "expected_secondary": r["expected_secondary"], "label_spoken": "no",
                         "text": r["text"], "audio_file": ""})
    in_prompt = {text for text, _, _ in EXAMPLES}
    for r in rows:
        r["in_prompt"] = "yes" if r["text"] in in_prompt else "no"
    unknown = {r["expected"] for r in rows} - set(REASONS)
    if unknown:
        sys.exit(f"Expected codes missing from taxonomy.py: {unknown}")
    return rows


async def run_live(rows, args):
    import main  # needs SARVAM_API_KEY

    async with main.http_client(args.timeout) as client:
        llm = main.returns_llm(client)
        for i, row in enumerate(rows, 1):
            t0, steps, text = time.monotonic(), [], row["text"]
            try:
                if args.audio_dir and row["audio_file"]:
                    path = Path(args.audio_dir).expanduser() / row["audio_file"]
                    stt, stt_row = await main.transcribe(client, path.read_bytes(), path.name, "audio/mpeg")
                    steps.append(stt_row)
                    text = (stt.get("transcript") or "").strip()
                    row["transcript"] = text
                result, llm_steps = await returns.classify_return(
                    text, llm, use_evaluator=not args.no_evaluator, second_opinion=args.second_opinion)
                steps += llm_steps
                row.update(status=result.status, reason_code=result.reason_code,
                           secondary=result.secondary_reason_code or "", confidence=result.confidence,
                           route=result.route, review_hint=result.review_hint or "",
                           readings_agree="" if result.readings_agree is None else str(result.readings_agree))
            except Exception as e:  # keep going: one failed row must not lose the run
                row.update(status="error", reason_code="", secondary="", confidence="", route="",
                           review_hint="", error=f"{type(e).__name__}: {e}"[:200])
            row["seconds"] = round(time.monotonic() - t0, 2)
            row["cost_inr"] = round(sum(s["cost_inr"] for s in steps), 5)
            row["calls"] = len(steps)
            print(f"[{i}/{len(rows)}] {row['id']:<12} {row['status']:<13} {row['reason_code']:<24} {row['seconds']}s", flush=True)
            await asyncio.sleep(args.pause)


def pct(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


def summarise(rows, name) -> str:
    def correct(r):
        got, want = r["reason_code"], r["expected"]
        # Any "unclassifiable" reason counts as right when one was expected: all three mean Needs Review.
        return bool(got) and (got == want or (is_unclear(got) and is_unclear(want)))

    def owner_ok(r):  # routed to the right team, even if the exact reason differs
        return bool(r["reason_code"]) and REASONS[r["reason_code"]].owner == REASONS[r["expected"]].owner

    def lenient(r):  # label found as primary or secondary
        return correct(r) or (r["secondary"] and r["secondary"] == r["expected"])

    lab = [r for r in rows if r["set"] == "labelled"]
    hard = [r for r in rows if r["set"] == "hard"]
    out = [f"Run: {name}", f"Settings: {returns.run_meta()}", ""]
    for title, group in (("Labelled voice-pack transcripts", lab), ("Hard cases", hard)):
        if not group:
            continue
        done = [r for r in group if r["status"] != "error"]
        classified = [r for r in done if r["status"] == "classified"]
        out += [
            f"== {title}: {len(group)} rows ==",
            f"Exact match with the label:            {pct(sum(map(correct, done)), len(group))}",
            f"Match as primary or secondary:         {pct(sum(1 for r in done if lenient(r)), len(group))}",
            f"Routed to the right owner:             {pct(sum(1 for r in done if owner_ok(r)), len(group))}",
            f"Precision when it did classify:        {pct(sum(map(correct, classified)), len(classified))}",
            f"Marked Needs Review:                   {pct(sum(r['status'] == 'needs_review' for r in done), len(group))}",
            f"Errors (API failures):                 {pct(len(group) - len(done), len(group))}",
            f"Small/large direction flips:           {sum((r['expected'] in SMALL and r['reason_code'] in LARGE) or (r['expected'] in LARGE and r['reason_code'] in SMALL) for r in done)}",
        ]
        plain = [r for r in group if r["label_spoken"] == "no" and r["status"] != "error"]
        if len(plain) != len(done):
            out.append(f"Exact match, excluding clips that read the label aloud: {pct(sum(map(correct, plain)), len(plain))}")
        unseen = [r for r in done if r["in_prompt"] == "no"]
        if len(unseen) != len(done):
            out.append(f"Exact match, excluding rows used as prompt examples:    {pct(sum(map(correct, unseen)), len(unseen))}")
        out.append("")
    timed = [r for r in rows if r.get("seconds") is not None and r["status"] != "error"]
    if timed:
        secs = sorted(r["seconds"] for r in timed)
        cost = [r["cost_inr"] for r in timed]
        out += [
            "== Speed, cost, routing ==",
            f"Seconds per return: median {statistics.median(secs):.1f}, 90th percentile {secs[int(0.9 * (len(secs) - 1))]:.1f}, slowest {secs[-1]:.1f}",
            f"Cost per return:    mean ₹{statistics.mean(cost):.4f}, total for this run ₹{sum(cost):.2f}",
            f"Sent to evaluator:  {pct(sum(r['route'] == 'evaluator' for r in timed), len(timed))}",
            f"Stopped by the code guard: {sum(r['route'] == 'guard' for r in timed)}",
            f"Model calls per return: mean {statistics.mean(r['calls'] for r in timed):.2f}",
            "",
        ]
    compared = [r for r in timed if r.get("readings_agree") in ("True", "False")]
    if compared:
        dis = [r for r in compared if r["readings_agree"] == "False"]
        agreed_wrong = [r for r in compared if r["readings_agree"] == "True" and not correct(r)]
        out[-1:-1] = [
            f"Two readings disagreed: {pct(len(dis), len(compared))}",
            f"  of those, final answer correct: {pct(sum(map(correct, dis)), len(dis))}",
            f"Both readings agreed but were wrong: {len(agreed_wrong)}",
        ]
    wrong = [r for r in rows if r["status"] != "error" and not correct(r)]
    out.append(f"== Rows that did not match exactly: {len(wrong)} ==")
    for r in wrong:
        got = r["reason_code"] + (f" + {r['secondary']}" if r["secondary"] else "") + (f" (hint {r['review_hint']})" if r["review_hint"] else "")
        out.append(f"{r['id']:<12} expected {r['expected']:<22} got {got:<40} | {r.get('transcript') or r['text']}"[:230])
    return "\n".join(out)


def main_cli():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--baseline", action="store_true", help="keyword rules only; no API calls")
    p.add_argument("--no-evaluator", action="store_true", help="ablation: skip the evaluator pass")
    p.add_argument("--second-opinion", action="store_true", default=None,
                   help="run two independent fast readings in parallel and compare them")
    p.add_argument("--script", choices=["roman", "devanagari"], default="roman", help="which transcript column to use")
    p.add_argument("--audio-dir", help="folder holding the unzipped voice pack; runs speech-to-text on each clip")
    p.add_argument("--limit", type=int, help="only the first N rows")
    p.add_argument("--only", choices=["labelled", "hard"], help="run one of the two sets")
    p.add_argument("--name", help="label for the output files")
    p.add_argument("--pause", type=float, default=0.5, help="seconds between rows (rate limit)")
    p.add_argument("--timeout", type=float, default=120)
    args = p.parse_args()

    rows = load_rows(args.script)
    if args.only:
        rows = [r for r in rows if r["set"] == args.only]
    if args.limit:
        rows = rows[:args.limit]
    name = args.name or ("baseline" if args.baseline else "voice" if args.audio_dir
                         else "no-evaluator" if args.no_evaluator else "second-opinion" if args.second_opinion
                         else f"live-{args.script}")
    if args.baseline:
        for r in rows:
            r.update(keyword_baseline(r["text"]))
    else:
        asyncio.run(run_live(rows, args))

    fields = ["id", "set", "expected", "expected_secondary", "status", "reason_code", "secondary", "confidence",
              "route", "readings_agree", "review_hint", "calls", "seconds", "cost_inr", "label_spoken", "in_prompt", "text", "transcript", "error"]
    with open(HERE / f"results-{name}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    summary = summarise(rows, name)
    (HERE / f"summary-{name}.txt").write_text(summary + "\n", encoding="utf-8")
    print("\n" + summary)
    print(f"\nSaved eval/results-{name}.csv and eval/summary-{name}.txt")


if __name__ == "__main__":
    main_cli()
