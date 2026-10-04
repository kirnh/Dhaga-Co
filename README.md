# Dhaga & Co. — Return Reasons Digest

Reads the "Other" box on returns that nobody reads, and tells Neha every week which SKUs and vendors to fix.

FDE Academy · Tech Track · Mini Project 1 · Group 8 (five members).

Live: https://dhaga.ctrlaltexist.com (password-protected; `/health` is open).

## 1. The problem

In Dhaga's words: "Forty-four percent of our returns get dumped into 'Other' with unread customer feedback, meaning we keep reordering and manufacturing items that don't fit right while our repeat purchase rate stays flat."

Owner: Neha, Category Head. She reads a few hundred "Other" entries by hand. The rest go unread.

| Number | Value | Source |
|---|---|---|
| Overall return rate | 31% | from the brief |
| Returns that land in "Other" | 44% | from the brief |
| Product reviews, 18 months, unread | 410,000 | from the brief |
| Repeat purchase rate, six quarters | 22% | from the brief |
| Orders per week | 48,000 | from the brief |
| Returns per week (48,000 × 31%) | 14,880 | arithmetic on the brief |
| "Other" returns per week (14,880 × 44%) | about 6,550 | arithmetic on the brief |
| Reversed GMV per week (14,880 × ₹840) | ₹1.25 crore | arithmetic on the brief |

Our biggest assumption: fit and sizing is the main thing hiding in "Other". If fit is under 15% of the classified text, we are wrong (Discovery note, section 7).

## 2. What it does

A tool for Neha's team. Nothing is sent to customers by a model.

1. **Read one return.** Typed text or a voice note (speech-to-text first). English, Hindi and Hinglish, Roman or Devanagari.
2. **Classify.** A fast model picks one of **61 reasons** (and a second reason if exactly two problems are stated). The reasons are grouped under 7 owners and live in `taxonomy.py`, the only place they are defined.
3. **Validate.** Code checks the reply against a schema and the reason list. A bad reply gets one retry with the error fed back.
4. **Doubt goes up a level.** Low confidence, invalid output, or (optionally) two readings that disagree go to a slower evaluator.
5. **No guessing.** Still unsure, or the text looks like an instruction to the system: **Needs Review**. A human settles it.
6. **Keep it.** Every result is stored, with the SKU and vendor if the caller sends them.
7. **Weekly digest.** Code counts classified returns per SKU and vendor, flags the unusual ones, and names who fixes each:

| Problem group | Goes to |
|---|---|
| Fit and size | Neha (catalogue, size charts) |
| Product quality | Vendor QC (Tiruppur, Jaipur) |
| Not as described | Vivek (listing team, product copy) |
| Fulfilment error | Warehouse (Unicommerce, three FCs) |
| Delivery | Faizan (Delhivery, Shiprocket, Ekart) |
| Customer-side, no defect | Arpita and Sameer (policy, not product) |
| Unclassifiable | Needs a human |

**How the digest decides.** A SKU is flagged for a problem group when it has at least `DIGEST_MIN_COUNT` (default 5) classified returns in that group in the window **and** the group is at least `DIGEST_MIN_Z` (default 3) standard deviations more common on that SKU than the overall mix predicts. A z-score is used instead of "twice the usual share" because fit is already a large slice of all returns, so "twice as common" can be impossible for it (it would need over 100%). A vendor needs double the count.

Limits, stated plainly:
- It compares shares of returns, not return rates. The brief gives no units sold per SKU. When the orders table is joined in, swap the share for returns ÷ units sold and keep the same two-part threshold.
- At a threshold of 3, an occasional SKU still gets flagged by chance when dozens of SKU and group pairs are tested. Every finding shows example customer texts so Neha can check it before acting. The threshold is a starting point to tune with the client.
- Returns without a SKU are counted but cannot appear in the digest.

## 3. Where code ends and the model starts

| Step | Code or model | Why |
|---|---|---|
| Speech to text (voice only) | Model: `saaras:v4` | Messy audio, many languages |
| Block text that addresses the system ("ignore previous instructions", reason codes) | Code | Pattern match; the live run showed the model obeying such text, so no model sees it |
| Read the text into a reason | Model: `sarvam-105b`, reasoning off, temperature 0 | Judgment on messy language |
| Check the reply against the schema and the 61 codes | Code | Comparison |
| Re-read doubtful rows | Model: `sarvam-105b`, reasoning on (low), temperature 0 | Harder judgment, small share of rows |
| Compare two independent readings (optional, `RETURN_SECOND_OPINION=on`) | Code | Equality check |
| Map reason to owner | Code | Lookup table |
| Count per SKU and vendor, apply thresholds | Code | Counting and comparison |
| Settle a Needs Review item | Human | The brief wants a human step on purpose |

All model calls run at **temperature 0**: this is classification, not writing, and no model writes customer-facing text.

**Two-model rule, honestly.** The brief asks for at least two different models. Today the text path uses one LLM (`sarvam-105b`) twice with different reasoning settings, and the voice path adds a second model (`saaras:v4`). A cheaper first-pass model with `sarvam-105b` as the evaluator would be a cleaner split and would cut cost. It is not built, and we have not measured it.

## 4. Patterns used

| Pattern | Where | What breaks without it |
|---|---|---|
| Routing | Code decides: accept, straight to Needs Review, or on to the evaluator | Either the slow model runs on every row, or doubtful rows are accepted |
| Prompt chaining | Transcribe, classify, validate, store, aggregate | One prompt that also counts and routes: counts drift and nobody can see which step failed |
| Evaluator-optimizer | Schema check, retry with the error, evaluator, then Needs Review | Malformed or invented codes flow into the digest unnoticed |
| Parallelization (optional) | Two independently worded fast readings at once, compared by code | The model reports 0.8–1.0 confidence even when wrong, so confidence alone cannot catch its mistakes |

## 5. Run it in five minutes

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env     # then fill in SARVAM_API_KEY and APP_PASSWORD
uv run uvicorn main:app --reload
uv run pytest            # 110 tests, Sarvam is faked, no key or network needed
```

Open http://127.0.0.1:8000 and sign in with `APP_PASSWORD`.

Variables (names only; values go in `.env`, never committed). Everything except the first two is optional, with defaults in `.env.example`:

- `SARVAM_API_KEY`, `APP_PASSWORD` (required; unset password means nobody can sign in)
- `RETURN_CONFIDENCE_THRESHOLD`, `RETURN_CLASSIFIER_MODEL`, `RETURN_CLASSIFIER_EFFORT`, `RETURN_EVALUATOR_MODEL`, `RETURN_EVALUATOR_EFFORT`, `RETURN_EVALUATOR_MAX_TOKENS`, `RETURN_SECOND_OPINION`, `RETURN_TIMEOUT_S`
- `RETURNS_DB` (SQLite file, default `data/returns.db`), `DIGEST_MIN_COUNT`, `DIGEST_MIN_Z`
- `SARVAM_STT_MODEL`, `SARVAM_LLM_MODEL`, `STT_INR_PER_HOUR`, `LLM_INR_PER_M_INPUT`, `LLM_INR_PER_M_OUTPUT`, `INR_PER_USD`

**See the digest without any real data or API key:**

```bash
uv run python eval/seed_demo.py          # 480 SYNTHETIC returns, stored with source='demo'
# then, signed in:  GET /api/returns/digest?source=demo
```

The seeder plants two clusters (fit on one SKU, stitching on another) so there is something to find. Demo rows never mix into `source=live` numbers.

### The customer screen and the demo orders

Customer flow: pick an item from an order, then voice (default), an uploaded voice file (backup), or text. A confident, consistent answer is accepted with no question, and the last screen shows every tier: category, reason, any second issue and details. The last screen is also the **return page**: what the customer gave us (the voice note with playback and its transcript, or the typed text, or "chosen from the list"), how it was read, who decided, and a "Change reason" button. The orders page links every requested item to it ("View"), and that state comes from the server, so it survives a reload. If the model cannot tell, the item is marked **unclear** for the team and the customer is asked nothing more. The two-level list (category, then reason) exists only as a choice the customer makes ("Choose from a list instead") or after saying No to a confirm. Add `?staff` to the URL to see owner, route, confidence and cost on the last screen.

**Direction check (code).** The model once answered "too tight around my waist" with `LOOSE_AT_WAIST` at 1.0 confidence, so confidence cannot catch it. `returns.direction_conflict()` compares tight/loose and short/long words (English, Hinglish, Devanagari) with the direction of the reason. A clear opposite sets `needs_confirm` and the screen asks "Did we get that right?". It never changes the reason. Text that mentions both sides is left alone.

| Order | Item to return | Say or type | Result |
|---|---|---|---|
| DH-24101 (COD, Delhivery) | Cotton kurti, mustard | "Maine medium size order kiya tha lekin bahut loose hai." (voice) | Size too large, accepted, no question |
| DH-24102 (prepaid, Shiprocket) | Floral maxi dress | "Size loose hai and stitching bhi open ho rahi hai." | Size too large + stitching came apart; two owners, one Tiruppur SKU |
| DH-24103 (prepaid, Ekart) | A-line dress, navy | "The dress is too tight around my waist." | The failure, shown on purpose: model says Loose at waist (1.0), the check asks the customer, "No" leads to the tiles, the corrected reason is stored |

SKU codes, vendor names and order ids are placeholders (`orders.py`); prices and carriers follow the brief.

### API

All routes except `/health` need the session cookie from `POST /login`.

| Route | What it does |
|---|---|
| `POST /api/returns/analyse` | Form field `text` **or** file `file` (voice, max 10 MB, kept for playback), optional `sku`, `vendor`, `order_id`, and `return_id` to change an earlier return (rewritten in place, so nothing is counted twice; refused with 409 once the team has settled it). Returns status, reason, owner, confidence, cost rows and `saved_id`. |
| `GET /api/orders` | The three demo orders (2-3 items each) the customer picks a return from. No orders feed exists in this MVP. Each item carries a `return` summary once one exists, so the page can link to it. |
| `GET /api/returns/{id}` | One return as the customer sees it: raw input (typed text, or the transcript and an `audio_url`), category, reason, second issue, details, who decided (system, customer or team), `can_update`. |
| `GET /api/returns/{id}/audio` | The customer's own voice note, for playback. |
| `POST /api/returns/choose` | Form `reason_code`, optional `sku`, `vendor`, `return_id`, `text`. The customer picked the reason from the tiles: stored (`route=customer`), replaces the model's row when `return_id` is given. "Something else" goes to the Needs Review queue. No model call. |
| `GET /api/returns/taxonomy` | The two-level reason list, generated from `taxonomy.py` |
| `GET /api/returns/review?state=open\|resolved` | The Needs Review queue (also holds "pending" returns the model could not reach) |
| `POST /api/returns/review/{id}/resolve` | Form `reason_code` (must be a specific reason from the list), optional `note`. Settles an item once. |
| `GET /api/returns/stats` | Share classified, route mix, top reasons, total and average cost |
| `GET /api/returns/digest?days=7&min_count=&min_z=&source=live` | The weekly digest, grouped by owner |
| `POST /api/parse` | The older generic voice-note parser. Kept, but **not part of the returns flow** (temperature 0.2, no schema check). |

## 6. What happens when it's wrong

- **Needs Review.** Anything the models are not sure about, or that looks like an instruction to the system, is never guessed into a category. It goes to the queue.
- **Model down.** The API answers 503 with "saved for retry" and keeps the text (or the transcript) on the server, so it is not lost. If speech-to-text itself fails, there is nothing to keep.
- **Storage down.** The customer still gets the answer; `saved_id` is `null`.
- **The bar.** We aim for 90% agreement with a 200-row labelled set. See section 7 for where we are.
- **Failure case shown on purpose.** *"The dress is too tight around my waist."* The model returns `LOOSE_AT_WAIST` at confidence 1.0, which is wrong. Measured in the live run on 3 Oct, not fixed. Cause: the 61-reason list has "loose at waist" and "tight at chest" but no "tight at waist"; the list says to use `SIZE_TOO_SMALL`, and the model does not follow it. It shows why confidence cannot be trusted. Possible fixes, each a team decision: add "tight at waist" (and "loose at chest") to the list, or add a code check on the tight/loose direction.

## 7. Metric and measured results

Success measures:

- **Share of "Other" returns classified instead of sent to review.** Live in `GET /api/returns/stats` once real returns flow in.
- **Agreement with a labelled set.** See below.

Return rate is a lagging metric. It moves weeks after a size chart is fixed, so we only follow it on flagged SKUs 4–6 weeks after the fix. The Discovery note targets 31% down to 26–27% over two collection cycles.

### Measured on live Sarvam (3 Oct, run 2, taxonomy `team-61-2026-10-03b`)

| Set | Rows | Exact match | Right owner |
|---|---|---|---|
| Labelled voice-pack transcripts | 84 | 73 (87%) | 78 (93%) |
| Hard cases | 38 | 33 (87%) | 37 (97%) |
| Keyword baseline, same rows | 84 / 38 | 70 / 14 | n/a |

Median 0.8 s per return, about ₹0.08 per return, no small/large direction flips.

**Read these numbers with care.** The hints were tuned after seeing these rows, and the rows are synthetic, so 87% is not an independent score.

### Held-out set (added, not yet run on the model)

`eval/heldout_cases.csv` has 78 new rows written for the 61 reasons after the prompt was frozen: at least 55 of the 61 reasons, Hinglish, English and Devanagari, two-reason cases, near-miss pairs and one injection. With the 84 and 38 rows above the labelled set is **200 rows**. Do not tune the hints on it.

- The held-out rows were drafted by Claude, not hand-labelled by the team. Someone on the team should review the labels before the score is quoted as "agreement with hand labels".
- The keyword baseline scores **26% (20/78)** on this set, against 83% on the voice pack, so the voice pack is the easy set.
- The model has not been run on it yet. That needs the API key: `uv run python eval/run_eval.py --only heldout` (about ₹6).
- `--second-opinion` has been built but never measured.

### Cost (measured per return, arithmetic at volume)

```
Per return, measured:        ₹0.08   (our 3 Oct live run)
"Other" returns only:        6,550 per week × ₹0.08  = about ₹524 per week
Every return (14,880/wk):    14,880 × ₹0.08          = about ₹1,190 per week
Per year, every return:      ₹1,190 × 52             = about ₹62,000
Voice adds speech-to-text:   ₹30 per audio hour (Sarvam list price in main.py, verify)
Volumes are from the brief. The ₹0.08 is from our run on synthetic text; real returns may be longer.
```

## 8. Status

**Built and working**
- Classifier with the 61-reason list, schema validation, retry, evaluator, injection guard and Needs Review (`returns.py`, `taxonomy.py`)
- Text and voice input; the page has Type it, Voice note and Pick from list (`static/index.html`)
- Storage, Needs Review queue API, stats and the weekly digest API (`store.py`, `digest.py`, `main.py`)
- Evaluation: 200 labelled rows, keyword baseline, live runner (`eval/`)
- Docker, AWS EC2 deploy with HTTPS, password gate
- 110 tests

**Not built**
- **No screen for the team yet.** The Needs Review queue and the digest are APIs only; `static/index.html` is still the customer form.
- **No SKU or vendor on the customer screen.** The API accepts them, but the form does not send them.
- The model has not been run on the held-out set; `--second-opinion` has not been measured.
- The evaluator is slow and often returns nothing within its token budget; one Sarvam call took 61 s against our 30 s timeout.
- Model confidence is 0.8–1.0 even when wrong, so the 0.75 threshold rarely triggers.
- Not tried on a real phone.
- Two-model split (see section 3).

## 9. Open questions for the client

From Appendix C of the Discovery note. The brief does not answer them, so we have not guessed.

- Is the 31% on orders shipped or delivered, and does it include RTO?
- What does one return cost end to end (reverse pickup, inspection, refund handling)?
- What share of returned stock is resold versus written off, given the six-week pull?
- What options are in the return-reason dropdown today, and how is "Other" worded to the customer?
- Is a size chart shown in the app, and whose chart is it?
- Is there an exchange flow, or only refunds?
- GMV check: 48,000 × 52 × ₹840 is about ₹210 crore, not the ₹310 crore in the brief. Which measure is GMV?
- Units sold per SKU, so the digest can use return rates instead of shares of returns.
- Which SKU and vendor does each return belong to, and where do we read it from?

Ours, still open: the digest thresholds and the model choice.

## 10. Team

| Role | Name |
|---|---|
| Discovery | TBD |
| Workflow and patterns | TBD |
| Frontend | TBD |
| Deployment and README | TBD |
| Pitch and cost | TBD |

## Not leading with

The other two problems we looked at are kept in the team's local `docs/` folder (not in this public repo): COD return-to-origin (about ₹9.1 lakh per week, Faizan) and where-is-my-order tickets (58% of about 9,000 per week, Arpita). Both sit below returns because of how they depend on fit and listing quality (RTO) or are mostly lookup (WISMO).

## Deployment

Live URL: https://dhaga.ctrlaltexist.com (AWS EC2 `t3.micro` in `ap-south-1`, built from the `Dockerfile`, Caddy in front for HTTPS).

Check it is up: `curl https://dhaga.ctrlaltexist.com/health` returns `{"status":"ok"}`. This needs no API key.

Redeploy: every push or merge to `main` deploys automatically (`.github/workflows/deploy.yml`). The workflow opens SSH to its own runner IP for the duration of the deploy, copies the app, rebuilds the container, closes SSH, then checks `/health`. Repo secrets it needs: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (an IAM user that can edit the security group), `EC2_SSH_KEY` (the private key contents), `SARVAM_API_KEY` and `APP_PASSWORD`.

**Data survives redeploys.** The returns database is `/home/ubuntu/dhaga-data/returns.db` on the server, mounted into the container at `/home/user/app/data`. It holds customer text: back it up before deleting the instance, and never commit it.

Manual redeploy, from the repo root (copy every module, not only `main.py`):

```bash
scp -i ~/.ssh/dhaga-key.pem -r *.py static pyproject.toml uv.lock .python-version Dockerfile .dockerignore ubuntu@<elastic-ip>:/home/ubuntu/app/
ssh -i ~/.ssh/dhaga-key.pem ubuntu@<elastic-ip> 'cd app && docker build -q -t dhaga . && docker rm -f dhaga; mkdir -p /home/ubuntu/dhaga-data && docker run -d --name dhaga --restart unless-stopped --env-file /home/ubuntu/dhaga.env -v /home/ubuntu/dhaga-data:/home/user/app/data -p 127.0.0.1:7860:7860 dhaga'
```

Caddy (HTTPS, auto-renewing certificate) proxies the domain to the container. SSH is open only to one IP; if yours changes, update the `dhaga-sg` security group. Health check path: `/health`.

Secrets: kept in GitHub repo secrets only. Each deploy writes `SARVAM_API_KEY` and `APP_PASSWORD` to a root-only env file on the server (`/home/ubuntu/dhaga.env`, mode 600) and starts the container with `--env-file`. Never in the repo or the image. To rotate a key, update the GitHub secret and re-run the deploy.

Cold start: the EC2 instance stays on, so there is no cold start. Before a demo, open `/health` once to confirm it answers.

Password gate: the site first shows a login page; the shared password is the `APP_PASSWORD` GitHub secret (generate with `python -c "import secrets; print(secrets.token_urlsafe(16))"`). A correct password sets a 30-day HttpOnly cookie. `/health` stays open. To rotate, update the secret and re-run the deploy; everyone is signed out.
