# Returns classifier: status and hand-off (3 Oct 2026)

Branch `feature/sandeep-returns-classifier`. Merging to `main` deploys it and replaces the live screen.

## What is built
- `taxonomy.py`: the 61 reasons, 7 owner groups, hints and prompt examples. The only place reasons live.
- `returns.py`: `classify_return()`, used by both text and voice. Fast first pass (reasoning off),
  schema validation with one retry, code guard for injected instructions, evaluator for
  invalid or low-confidence output, Needs Review instead of guessing.
- `main.py`: `POST /api/returns/analyse` (form field `text` OR file field `file`). `/api/parse` unchanged.
- `eval/`: 84 labelled transcripts + 38 hard cases, `run_eval.py`.
- `tests/`: 77 tests, Sarvam faked. `uv run pytest`.

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

## The screen (`static/index.html`)
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
- Needs Review list for the team.
- README rewrite (it still describes the batch digest and says "not deployed yet").

## Run the evaluation
    cp .env.example .env        # add SARVAM_API_KEY and APP_PASSWORD
    uv run python eval/run_eval.py --baseline         # free
    uv run python eval/run_eval.py                    # about ₹10
    uv run python eval/run_eval.py --second-opinion   # about ₹20, not yet run
