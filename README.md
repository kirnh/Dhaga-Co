# Dhaga & Co. — Return Reasons Digest

Reads the "Other" box on returns that nobody reads, and tells Neha every week which SKUs and vendors to fix.

FDE Academy · Tech Track · Mini Project 1 · Group 8 (five members).

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

This is a batch report for Neha. It is not a customer-facing bot. Nothing reaches customers.

1. Take past return text from the "Other" box.
2. A cheap model turns each one into JSON: a **list** of reasons (one return can have several), fit direction (too small or too big), body area, and a confidence score.
3. Code checks the JSON against a schema. Bad JSON gets one retry.
4. Rows with low confidence go to a stronger model for a second read.
5. Rows still unsure go to an on-screen "unclear" queue. We do not guess.
6. Code counts reasons per SKU and vendor each week. Only SKUs over a threshold appear in the digest.
7. Each finding is routed to the team that can fix it:

| Finding | Goes to |
|---|---|
| Fit | Listing team (size chart) |
| Colour or photo | Studio |
| Defect | Sourcing |
| Wrong item | Warehouse |

Neha reads the digest and decides. The threshold is not set yet (see Open questions).

## 3. Where code ends and the model starts

| Step | Code or model | Why |
|---|---|---|
| Load "Other" text from the returns data | Code | Lookup |
| Read messy, Hinglish return text into reasons | Cheap model, temperature 0 | Judgment on messy language |
| Check the JSON against the schema | Code | Comparison |
| Re-read low-confidence rows | Stronger model, temperature 0 | Harder judgment, on a small share of rows |
| Count per SKU and vendor, apply threshold | Code | Counting and comparison |
| Map reason to team | Code | Lookup table |
| Decide which fixes to act on | Human (Neha) | The brief wants a human step on purpose |

Model names: **TBD**. Both models run at temperature 0, because this is classification, not writing.

## 4. Patterns used

| Pattern | Where | What breaks without it |
|---|---|---|
| Routing | Cheap model first; low-confidence rows go to the stronger model | Either we pay the strong-model price on every row, or we accept weak answers on the hard ones |
| Prompt chaining | Read text, extract JSON, validate, aggregate | One big prompt that also counts and routes. Counts drift and nobody can see which step failed |
| Evaluator-optimizer (validation) | Schema check, retry once, then stronger model, then the unclear queue | Malformed or invented fields flow into the digest unnoticed |

## 5. Run it in five minutes

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env     # .env.example does not exist yet, see Status
# fill in the variables below, then:
uv run uvicorn main:app --reload
```

Open http://127.0.0.1:8000.

Variables read by `main.py` today (names only; values go in `.env`, which must never be committed):

- `SARVAM_API_KEY` (required)
- `SARVAM_STT_MODEL`, `SARVAM_LLM_MODEL`
- `STT_INR_PER_HOUR`, `LLM_INR_PER_M_INPUT`, `LLM_INR_PER_M_OUTPUT`
- `LLM_REASONING_EFFORT`, `LLM_MAX_TOKENS`
- `INR_PER_USD`

Live URL: _not deployed yet_ (AWS EC2, Docker, FastAPI). We first planned Hugging Face Spaces (Docker), but our account can only create Static Spaces, which cannot run FastAPI.

## 6. What happens when it's wrong

- **Unclear queue.** Anything the models are not sure about is shown on screen as "unclear". It is never guessed into a category.
- **The bar.** We aim for 90% agreement with a 200-row hand-labelled set. Below that, we say so in the demo.
- **Failure case shown on purpose.** Not chosen yet. A candidate (our proposal): a return that mixes a fit complaint and a defect in Hinglish, to show the list schema and the unclear queue working.

## 7. Metric

- Share of "Other" returns that get classified (not sent to "unclear").
- Agreement with the 200 hand-labelled rows.

Return rate is a lagging metric. It moves weeks after a size chart is fixed. We only track it as a follow-up, on flagged SKUs 4–6 weeks after the fix. The Discovery note targets 31% down to 26–27% over two collection cycles.

### Cost (our estimate)

Prices and token counts below are placeholders from the proposal check, not the models we will choose.

```
Returns:        48,000 × 31%             = 14,880 per week        (from the brief)
"Other" only:   14,880 × 44%             = about 6,550 per week
Per return:     cheap 2,200 in / 210 out at $1 / $5 per M   = $0.0033
                15% re-read, 1,200 in / 150 out at $3 / $15 per M
                                         = $0.0059 × 0.15   = $0.0009
                                         total              = about $0.0041
Per week:       6,550 × $0.0041          = about $27
In rupees:      $27 × ₹85                = about ₹2,300 per week
Per year:       ₹2,300 × 52              = about ₹1.2 lakh
```

For reference, the same per-return cost on all 14,880 returns is about $62 per week (₹5,300 per week).

## 8. Status

Today the repo holds the docs only. The code below lives in a separate folder (`../P1`) and has not been moved in yet.

**Exists (from reading the code; not re-run for this README):**
- `main.py`: a FastAPI voice-note parser. Audio goes to speech-to-text, then to an LLM that returns JSON.
- Per-step cost tracking in INR and USD (`INR_PER_USD` defaults to 88).
- `static/index.html`: upload form, parsed result, transcript, cost table.

**Missing against the brief:**
- The returns pipeline itself (schema, classifier, digest)
- A second model for low-confidence rows (today: one LLM)
- Temperature 0 (today: 0.2)
- Output validation against a schema (today: loose JSON parse, no retry)
- The unclear queue and the weekly digest screens
- The 200-row hand-labelled set
- A Dockerfile and the deploy

The voice-note parser is an optional input channel. We build it in only if time allows, after the core work.

## 9. Open questions for the client

From Appendix C of the Discovery note. The brief does not answer them, so we have not guessed.

- Is the 31% on orders shipped or delivered, and does it include RTO?
- What does one return cost end to end (reverse pickup, inspection, refund handling)?
- What share of returned stock is resold versus written off, given the six-week pull?
- What options are in the return-reason dropdown today, and how is "Other" worded to the customer?
- Is a size chart shown in the app, and whose chart is it?
- Is there an exchange flow, or only refunds?
- GMV check: 48,000 × 52 × ₹840 is about ₹210 crore, not the ₹310 crore in the brief. Which measure is GMV?

Ours, still open: the digest threshold, and the model names.

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

Check it is up: `curl <live-url>/health` returns `{"status":"ok"}`. This needs no API key.

Redeploy: every push or merge to `main` deploys automatically (`.github/workflows/deploy.yml`). The workflow opens SSH to its own runner IP for the duration of the deploy, copies the app, rebuilds the container, closes SSH, then checks `/health`. Repo secrets it needs: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (a deploy-only IAM user) and `EC2_SSH_KEY` (the private key contents).

Manual redeploy, from the repo root:

```bash
scp -i ~/.ssh/dhaga-key.pem -r main.py static pyproject.toml uv.lock .python-version Dockerfile .dockerignore ubuntu@<elastic-ip>:/home/ubuntu/app/
ssh -i ~/.ssh/dhaga-key.pem ubuntu@<elastic-ip> 'cd app && docker build -q -t dhaga . && docker rm -f dhaga; docker run -d --name dhaga --restart unless-stopped -p 127.0.0.1:7860:7860 dhaga'
```

Caddy (HTTPS, auto-renewing certificate) proxies the domain to the container. SSH is open only to one IP; if yours changes, update the `dhaga-sg` security group. Health check path: `/health`.

Secrets: not set yet. When needed, add `SARVAM_API_KEY` to a root-only env file on the instance and pass it with `docker run --env-file`, never in the repo or the image.
- `SARVAM_API_KEY` (required for the voice parser)
- Optional overrides: `SARVAM_STT_MODEL`, `SARVAM_LLM_MODEL`, `STT_INR_PER_HOUR`, `LLM_INR_PER_M_INPUT`, `LLM_INR_PER_M_OUTPUT`, `LLM_REASONING_EFFORT`, `LLM_MAX_TOKENS`, `INR_PER_USD`

Cold start: the EC2 instance stays on, so there is no cold start. Before a demo, open `/health` once to confirm it answers.
