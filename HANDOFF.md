# Returns classifier: status and hand-off (3 Oct 2026, updated)

Branch `feature/needs-review-and-docs` (backend and docs only, **no frontend change**). Merging to `main` deploys it. `.github/workflows/deploy.yml` now mounts a data folder on the server: have a teammate read that change before merging.

## What is built
- `taxonomy.py`: the 61 reasons, 7 owner groups, hints and prompt examples. The only place reasons live.
- `returns.py`: `classify_return()`, used by both text and voice. Fast first pass (reasoning off),
  schema validation with one retry, code guard for injected instructions, evaluator for
  invalid or low-confidence output, Needs Review instead of guessing.
- `main.py`: `POST /api/returns/analyse` (form field `text` OR file field `file`). `/api/parse` unchanged.
- `eval/`: 84 labelled transcripts + 38 hard cases + **78 held-out cases** (`heldout_cases.csv`, 200 in all), `run_eval.py` (`--only heldout`), `seed_demo.py` (synthetic data for the digest demo).
- `store.py`: SQLite store (`RETURNS_DB`, default `data/returns.db`). Every analysis is saved, with optional `sku` and `vendor`. Pending (model unreachable) returns are saved too.
- New API: `GET /api/returns/review`, `POST /api/returns/review/{id}/resolve`, `GET /api/returns/stats`, `GET /api/returns/digest`. `/api/returns/analyse` takes optional `sku`, `vendor` and returns `saved_id`.
- `digest.py`: weekly per-SKU and per-vendor digest, count threshold plus z-score, owner looked up from the taxonomy. Code only, no model.
- `README.md` rewritten and `BUILD_NOTE.md` added (the brief's two-page build note).
- `tests/`: 110 tests, Sarvam faked. `pytest` (uv cannot download behind Avast; plain `python -m pytest` works with the packages installed).

## Measured on live Sarvam (run 2, 3 Oct, taxonomy version team-61-2026-10-03b)
- Labelled: 73/84 exact (87%), 78/84 to the right owner (93%), 0 small/large flips.
- Hard cases: 33/38 exact (87%), 37/38 right owner.
- Keyword baseline on the same rows: 70/84 and 14/38.
- Median 0.8 s and about ₹0.08 per return.
- Caveat: hints were tuned after seeing these rows, and the rows are synthetic. Not an independent score.

## Known problems
1. Demo case 1 fails: "The dress is too tight around my waist" -> LOOSE_AT_WAIST at confidence 1.0.
   The list has no "tight at waist" reason. Either add one (and "loose at chest") or demo a different sentence.
2. Model confidence is 0.8-1.0 even when wrong, so the 0.75 threshold rarely triggers.
   `--second-opinion` (two parallel readings, agreement checked by code) is built but NOT yet measured.
3. The evaluator (reasoning on) is slow and often returns nothing within its token budget.
4. Label disagreements: four "fabric feels cheap" clips say the listing named another fabric
   (model answers FABRIC_UNLIKE_DESCRIPTION); kids clips labelled "size too large".
5. One Sarvam call took 61 s. The app times out at 30 s and shows "saved for retry".

## Customer screen, rebuilt (4 Oct 2026; supersedes "The screen" below)
- `static/index.html` is now: orders page (`orders.py`, 3 demo orders, 2-3 items each) -> tap an item -> big mic (default, stopping the recording submits) or "Prefer typing?" -> accepted silently when confident, "Did we get that right?" when the direction check (`returns.direction_conflict`) flags it, category tiles then reason rows when the model cannot tell or the customer says No.
- Customer-friendly category names live in `taxonomy.CUSTOMER_LABELS`. `sku` and `vendor` are now sent. The customer's own pick is stored via `POST /api/returns/choose`, so it reaches the digest.
- Demo script and the three orders: README, "The customer screen and the demo orders". The failure case (known problem 1) is now caught by the check, not fixed in the reason list.
- The model call is faked in the browser test; **not tried on a real phone, a real microphone or live Sarvam**. Safari records mp4 audio: unchecked with Sarvam.
- The direction check is word-based, so "not tight" also asks for a confirm (one extra tap, never a wrong answer). Words beyond tight/loose/short/long are not covered.
- Needs Review and digest screens for the team are still not built.

## The screen (old, before 4 Oct)
- "Dhaga & Co. Returns": type a reason or send a voice note, then a result card with status,
  reason, second issue, details, confidence, and a collapsed team panel (owner, route, cost).
- Three ways in: "Type it", "Voice note" (language auto-detected) and "Pick from list".
- "Pick from list" is the team's two-level picker: 7 first-level categories, then the reasons under
  the chosen one. It is filled from `GET /api/returns/taxonomy` (i.e. from `taxonomy.py`), makes no
  model call and costs nothing. After an AI result, "Not right? Pick the reason yourself" opens the
  picker pre-set to what the model detected.
- A choice from the list is shown on screen only. Nothing is stored anywhere yet (there is no database).
- The first-level labels are the team's internal names ("Customer-side, no defect", "Unclassifiable").
  Consider customer-friendly wording before a real customer sees them.
- API or network failure shows "We couldn't analyse this right now..." and keeps the text in the
  browser (localStorage) for retry, including after a reload. A voice note is kept only while the page is open.
- To demo that failure: browser DevTools > Network > Offline, then press the button.
- Tested in headless Chromium at phone width against a faked Sarvam. Not yet tried on a real phone or with live Sarvam.
- The old Voice Note Parser page is replaced; `/api/parse` still exists.

## Not built yet
- **Frontend for the team:** a Needs Review screen (the API exists) and a digest screen. `static/index.html` is untouched and still the customer form. It does not send `sku` or `vendor`.
- **Held-out run:** `eval/heldout_cases.csv` has never been run on the model (needs `SARVAM_API_KEY`, about ₹6). Its labels were drafted by Claude: a teammate should review them. The keyword baseline scores 26% on it.
- `--second-opinion` still unmeasured. The evaluator is still slow (known problems 2, 3, 5 above).
- Known problem 1 (tight at waist) is documented as the demo's failure case; the fix (new reasons) is the team's decision. Held-out rows h-03 and h-06 test that area.
- **Two-model rule:** text path uses `sarvam-105b` for both passes. A cheaper first-pass model is not built.
- The digest compares shares of returns, not rates: units sold per SKU are not available. Thresholds (`DIGEST_MIN_COUNT=5`, `DIGEST_MIN_Z=3`) are untuned; a synthetic demo flagged one cluster by chance.
- Discovery note is not in the repo (`docs/` is gitignored). The brief wants it in the repo, dated before the first commit: team decision.
- Team names in the README are still TBD.

## Run the evaluation
    cp .env.example .env        # add SARVAM_API_KEY and APP_PASSWORD
    python eval/seed_demo.py                           # synthetic digest demo, no key needed
    uv run python eval/run_eval.py --baseline         # free
    uv run python eval/run_eval.py                    # about ₹10
    uv run python eval/run_eval.py --second-opinion   # about ₹20, not yet run
