"""Weekly digest for Neha: which SKUs and vendors keep coming back for the same kind of problem.

Pure code, no model. The model's job ended when it turned each return's free text into a
reason; here we only count, compare and look up who owns the fix.

A SKU is flagged for a problem group (fit, quality, ...) when BOTH hold:
  1. it has at least `min_count` classified returns in that group in the window, and
  2. that group is unusually common on this SKU: its count is at least `min_z` standard
     deviations above what the overall mix of returns predicts (a one-sided binomial z-score).

Why a z-score and not "twice the usual share": fit is already a big slice of all returns, so
"twice as common" can be impossible for it (it would need over 100%). The z-score adapts to
the base rate and to how many returns the SKU has: a small SKU needs a stronger skew than a
big one. min_z = 3 keeps false flags rare even when dozens of SKU and problem pairs are tested.

Why shares and not a return rate: the brief gives no units sold per SKU, so we cannot say
"8% of this SKU's orders came back". When the orders table is joined in, replace the share
with a real rate (returns / units sold) and keep the same two-part threshold.
"""

import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import store
import taxonomy

MIN_COUNT = int(os.getenv("DIGEST_MIN_COUNT", "5"))
MIN_Z = float(os.getenv("DIGEST_MIN_Z", "3.0"))
SAMPLES = 3  # example customer texts shown per finding, so Neha can check the label herself

# Who fixes what. Looked up from the taxonomy, never decided by a model.
ACTION = {
    "FIT": "Check the size chart and fit notes",
    "QUALITY": "Raise with the vendor's QC",
    "NOT_AS_DESCRIBED": "Fix photos, colour name or product copy",
    "FULFILMENT": "Check picking and packing at the fulfilment centre",
    "DELIVERY": "Review the courier on this lane",
    "CUSTOMER": "Policy question, not a product fault",
}


def _z(n: int, total: int, usual: float) -> float:
    """How many standard deviations n is above the n expected if this SKU followed the overall mix."""
    spread = math.sqrt(total * usual * (1 - usual))
    return (n - total * usual) / spread if spread else 0.0


def _finding(group: str, key: dict, n: int, total: int, overall_share: float, rows: list[dict]) -> dict:
    share = n / total
    reasons = Counter(taxonomy.REASONS[r["reason_code"]].label for r in rows)
    label, owner, _items = taxonomy.CATEGORIES[group]
    return {
        **key,
        "category": group,
        "category_label": label,
        "owner": owner,
        "action": ACTION.get(group, ""),
        "returns_in_group": n,
        "returns_total": total,
        "share": round(share, 3),
        "usual_share": round(overall_share, 3),
        "lift": round(share / overall_share, 2) if overall_share else None,
        "z": round(_z(n, total, overall_share), 1),
        "top_reasons": [{"reason": k, "n": v} for k, v in reasons.most_common(3)],
        "examples": [r["text"][:160] for r in rows[:SAMPLES]],
    }


def _flag(rows: list[dict], key_fields: tuple[str, ...], overall: Counter, overall_n: int,
          min_count: int, min_z: float) -> list[dict]:
    """Group rows by key_fields, then by problem group, and keep the groups that pass both thresholds."""
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[tuple(r[f] for f in key_fields)].append(r)
    out = []
    for key, items in buckets.items():
        by_group: dict[str, list[dict]] = defaultdict(list)
        for r in items:
            by_group[r["category"]].append(r)
        for group, grows in by_group.items():
            if group == taxonomy.UNCLEAR_CATEGORY:
                continue
            usual = overall[group] / overall_n
            n = len(grows)
            if n >= min_count and 0 < usual < 1 and _z(n, len(items), usual) >= min_z:
                out.append(_finding(group, dict(zip(key_fields, key)), n, len(items), usual, grows))
    return sorted(out, key=lambda f: (-f["z"], -f["returns_in_group"]))


def build(days: int = 7, min_count: int | None = None, min_z: float | None = None,
          source: str = "live", now: datetime | None = None) -> dict:
    """The digest for the last `days` days. Returns plain data for the API."""
    min_count = MIN_COUNT if min_count is None else min_count
    min_z = MIN_Z if min_z is None else min_z
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    rows = store.rows_since(since, source)

    with_sku = [r for r in rows if r["sku"]]
    for r in with_sku:
        r["vendor"] = r["vendor"] or "Unknown vendor"
    overall = Counter(r["category"] for r in with_sku)
    n = len(with_sku)

    skus = _flag(with_sku, ("sku", "vendor"), overall, n, min_count, min_z) if n else []
    # Vendor view: same test, but across all of a vendor's SKUs. A vendor needs more evidence
    # because it has more SKUs, so the count threshold is doubled.
    vendors = _flag(with_sku, ("vendor",), overall, n, min_count * 2, min_z) if n else []

    by_owner: dict[str, list[dict]] = defaultdict(list)
    for f in skus:
        by_owner[f["owner"]].append(f)

    return {
        "window_days": days,
        "since": since,
        "source": source,
        "thresholds": {"min_count": min_count, "min_z": min_z, "vendor_min_count": min_count * 2},
        "classified_returns": len(rows),
        "with_sku": n,
        "without_sku": len(rows) - n,  # cannot be placed on any SKU, so cannot appear in the digest
        "findings": skus,
        "vendor_findings": vendors,
        "by_owner": dict(by_owner),
        "method": ("A SKU is flagged when it has at least min_count classified returns in one problem group "
                   "and that group is at least min_z standard deviations more common on the SKU than the overall "
                   "mix predicts. This uses shares of returns, not return rates: units sold per SKU are not "
                   "available yet."),
    }
