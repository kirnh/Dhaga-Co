"""Where analysed returns are kept, so the team can see them after the page is closed.

One SQLite file (standard library, no server). Every analysed return is saved:
classified ones (so we can report the share classified), Needs Review ones (the
team's queue) and pending ones (the model was unreachable, so nothing is lost).

The file path comes from RETURNS_DB (default data/returns.db). In production it
must sit on a mounted volume, or it is wiped on every deploy (see deploy.yml).
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.getenv("RETURNS_DB", "data/returns.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS returns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('classified', 'needs_review', 'pending')),
    input_mode      TEXT NOT NULL,
    text            TEXT NOT NULL,
    language        TEXT,
    reason_code     TEXT,
    category        TEXT,
    owner           TEXT,
    secondary_code  TEXT,
    details         TEXT NOT NULL DEFAULT '[]',
    confidence      REAL,
    explanation     TEXT,
    review_hint     TEXT,
    route           TEXT,
    cost_inr        REAL NOT NULL DEFAULT 0,
    taxonomy_version TEXT,
    prompt_hash     TEXT,
    failed_step     TEXT,
    resolved_at     TEXT,
    resolved_code   TEXT,
    resolved_note   TEXT,
    sku             TEXT,
    vendor          TEXT,
    source          TEXT NOT NULL DEFAULT 'live'
);
CREATE INDEX IF NOT EXISTS returns_status ON returns (status, resolved_at);
"""

# Columns added after the first version. Applied to an older file on open.
LATER_COLUMNS = {"sku": "TEXT", "vendor": "TEXT", "source": "TEXT NOT NULL DEFAULT 'live'"}


@contextmanager
def _db():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(SCHEMA)
            have = {r["name"] for r in conn.execute("PRAGMA table_info(returns)")}
            for col, kind in LATER_COLUMNS.items():
                if col not in have:
                    conn.execute(f"ALTER TABLE returns ADD COLUMN {col} {kind}")
            conn.execute("CREATE INDEX IF NOT EXISTS returns_sku ON returns (sku, created_at)")
            yield conn
            conn.commit()
        finally:
            conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_result(source: dict, result: dict, costs: dict, meta: dict, sku: str | None = None,
                vendor: str | None = None, origin: str = "live", created_at: str | None = None) -> int:
    """Store a finished analysis (status classified or needs_review). Returns the row id.

    sku and vendor say which product the return is about (the weekly digest groups by them).
    origin='demo' marks synthetic rows so they are never mixed into real numbers."""
    with _db() as db:
        cur = db.execute(
            """INSERT INTO returns (created_at, status, input_mode, text, language, reason_code, category, owner,
                                    secondary_code, details, confidence, explanation, review_hint, route,
                                    cost_inr, taxonomy_version, prompt_hash, sku, vendor, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (created_at or _now(), result["status"], source["mode"], source["text"], source.get("detected_language"),
             result["reason_code"], result["primary_category"], result["owner"], result.get("secondary_reason_code"),
             json.dumps(result.get("details") or [], ensure_ascii=False), result.get("confidence"),
             result.get("explanation"), result.get("review_hint"), result.get("route"),
             costs.get("total_inr", 0), meta.get("taxonomy_version"), meta.get("prompt_hash"),
             sku, vendor, origin),
        )
        return cur.lastrowid


def save_pending(source: dict, failed_step: str, costs: dict, sku: str | None = None,
                 vendor: str | None = None) -> int:
    """The model could not be reached. Keep the text (or transcript) so the return is not lost."""
    with _db() as db:
        cur = db.execute(
            """INSERT INTO returns (created_at, status, input_mode, text, language, cost_inr, failed_step, sku, vendor)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (_now(), "pending", source["mode"], source["text"], source.get("detected_language"),
             costs.get("total_inr", 0), failed_step, sku, vendor),
        )
        return cur.lastrowid


def save_choice(reason_code: str, owner: str, category: str, status: str, sku: str | None = None,
                vendor: str | None = None, return_id: int | None = None, text: str = "") -> int:
    """The customer picked the reason themselves (tiles, or 'not right' on a confirm screen).

    With return_id, that earlier row (the model's answer, a Needs Review item or a pending one) is
    corrected in place and leaves the team's queue; otherwise a new row is made. route='customer'
    marks it, so it can be told apart from a model answer. Returns the row id."""
    with _db() as db:
        if return_id is not None:
            cur = db.execute(
                """UPDATE returns SET status = ?, reason_code = ?, category = ?, owner = ?, secondary_code = NULL,
                          confidence = NULL, review_hint = NULL, route = 'customer', explanation = 'Chosen by the customer.'
                   WHERE id = ? AND resolved_at IS NULL""",
                (status, reason_code, category, owner, return_id),
            )
            if cur.rowcount:
                return return_id
        cur = db.execute(
            """INSERT INTO returns (created_at, status, input_mode, text, reason_code, category, owner, route,
                                    explanation, sku, vendor, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), status, "list", text, reason_code, category, owner, "customer",
             "Chosen by the customer.", sku, vendor, "live"),
        )
        return cur.lastrowid


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["details"] = json.loads(d["details"] or "[]")
    return d


def review_queue(state: str = "open", limit: int = 200) -> list[dict]:
    """Returns the team still has to look at (state=open) or has already settled (state=resolved)."""
    if state not in ("open", "resolved"):
        raise ValueError("state must be 'open' or 'resolved'")
    where = ("status IN ('needs_review','pending') AND resolved_at IS NULL" if state == "open"
             else "resolved_at IS NOT NULL")
    order = "id ASC" if state == "open" else "resolved_at DESC"
    with _db() as db:
        rows = db.execute(f"SELECT * FROM returns WHERE {where} ORDER BY {order} LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def get(return_id: int) -> dict | None:
    with _db() as db:
        r = db.execute("SELECT * FROM returns WHERE id = ?", (return_id,)).fetchone()
    return _row(r) if r else None


def resolve(return_id: int, reason_code: str, note: str = "") -> dict | None:
    """The team settles a Needs Review or pending item. Returns the updated row, or None if no such item."""
    with _db() as db:
        cur = db.execute(
            """UPDATE returns SET resolved_at = ?, resolved_code = ?, resolved_note = ?
               WHERE id = ? AND status IN ('needs_review','pending') AND resolved_at IS NULL""",
            (_now(), reason_code, note.strip()[:500], return_id),
        )
        if cur.rowcount == 0:
            return None
    return get(return_id)


def stats() -> dict:
    """Numbers behind the README metric: share of returns the system could classify on its own."""
    with _db() as db:
        counts = {r["status"]: r["n"] for r in db.execute("SELECT status, COUNT(*) AS n FROM returns GROUP BY status")}
        routes = {r["route"]: r["n"] for r in db.execute(
            "SELECT route, COUNT(*) AS n FROM returns WHERE route IS NOT NULL GROUP BY route")}
        reasons = [dict(r) for r in db.execute(
            """SELECT reason_code, owner, COUNT(*) AS n FROM returns WHERE status = 'classified'
               GROUP BY reason_code, owner ORDER BY n DESC""")]
        cost = db.execute("SELECT COALESCE(SUM(cost_inr), 0) AS c FROM returns").fetchone()["c"]
        open_n = db.execute(
            "SELECT COUNT(*) AS n FROM returns WHERE status IN ('needs_review','pending') AND resolved_at IS NULL"
        ).fetchone()["n"]
    classified = counts.get("classified", 0)
    answered = classified + counts.get("needs_review", 0)  # pending has no answer yet, so it is not in the share
    total = answered + counts.get("pending", 0)
    return {
        "total": total,
        "classified": classified,
        "needs_review": counts.get("needs_review", 0),
        "pending": counts.get("pending", 0),
        "open_for_team": open_n,
        "share_classified": round(classified / answered, 4) if answered else None,
        "by_route": routes,
        "by_reason": reasons,
        "total_cost_inr": round(cost, 4),
        "avg_cost_inr": round(cost / total, 4) if total else None,
    }


def rows_since(since_iso: str, source: str = "live") -> list[dict]:
    """Classified returns on or after since_iso. source is 'live', 'demo' or 'all'."""
    if source not in ("live", "demo", "all"):
        raise ValueError("source must be 'live', 'demo' or 'all'")
    where, args = "status = 'classified' AND created_at >= ?", [since_iso]
    if source != "all":
        where += " AND source = ?"
        args.append(source)
    with _db() as db:
        rows = db.execute(f"SELECT * FROM returns WHERE {where} ORDER BY id", args).fetchall()
    return [_row(r) for r in rows]
