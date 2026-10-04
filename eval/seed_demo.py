"""Fill a database with SYNTHETIC returns so the weekly digest can be demoed.

    python eval/seed_demo.py                      # writes to RETURNS_DB (default data/returns.db)
    python eval/seed_demo.py --db /tmp/demo.db    # somewhere else
    python eval/seed_demo.py --clear              # remove earlier demo rows first

No model is called and no key is needed. Every row is stored with source='demo', so it never
mixes into real numbers: the digest reads source=demo only when asked (/api/returns/digest?source=demo).

What is synthetic here, so nobody mistakes it for client data:
  - the customer texts are the 84 voice-pack transcripts in labelled_samples.csv plus the 38 hard
    cases, each stored under its expected reason (the voice pack alone covers only fit and quality)
  - the SKU codes, vendor assignment and dates are invented
  - two SKUs are given a deliberate cluster (fit on one, stitching on another) so the digest has
    something to find. A real week will not look this tidy.
"""

import argparse
import csv
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

import store  # noqa: E402
import taxonomy  # noqa: E402

BY_REF = {r.ref: r.code for r in taxonomy.REASONS.values() if r.ref is not None}

# (sku, vendor). Vendors follow the brief: about forty partners, mostly Tiruppur and Jaipur.
CATALOGUE = [
    ("KRT-1042", "Jaipur Textiles"), ("KRT-1077", "Jaipur Textiles"), ("KRT-1103", "Rangoli Exports, Jaipur"),
    ("TOP-2210", "Tiruppur Knits"), ("TOP-2231", "Tiruppur Knits"), ("TOP-2290", "Arun Garments, Tiruppur"),
    ("DRS-3015", "Jaipur Textiles"), ("DRS-3044", "Rangoli Exports, Jaipur"),
    ("KID-4120", "Tiruppur Knits"), ("KID-4155", "Arun Garments, Tiruppur"),
    ("MEN-5008", "Arun Garments, Tiruppur"), ("MEN-5031", "Tiruppur Knits"),
]
HOT_FIT_SKU = "KRT-1042"      # many "too small" returns
HOT_QUALITY_SKU = "TOP-2231"  # many "stitching came apart"


def load_texts() -> dict[str, list[str]]:
    by_code: dict[str, list[str]] = {}
    with open(HERE / "labelled_samples.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            by_code.setdefault(BY_REF[int(r["reason_ref"])], []).append(r["roman_hinglish"])
    with open(HERE / "hard_cases.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if not taxonomy.is_unclear(r["expected"]):  # unclear rows are never classified, so never in the digest
                by_code.setdefault(r["expected"], []).append(r["text"])
    return by_code


def fake_result(code: str) -> dict:
    r = taxonomy.REASONS[code]
    return {"status": "classified", "reason_code": code, "primary_category": r.category, "owner": r.owner,
            "secondary_reason_code": None, "details": [], "confidence": 0.9, "explanation": "synthetic demo row",
            "route": "first_pass"}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", help="database file (default: RETURNS_DB or data/returns.db)")
    p.add_argument("--clear", action="store_true", help="delete earlier demo rows first")
    p.add_argument("--rows", type=int, default=480, help="how many synthetic returns")
    p.add_argument("--days", type=int, default=7, help="spread them over this many days")
    args = p.parse_args()
    if args.db:
        store.DB_PATH = args.db

    rng = random.Random(7)  # fixed, so the demo looks the same every time
    texts = load_texts()
    codes = list(texts)
    fit = [c for c in codes if taxonomy.REASONS[c].category == "FIT"]
    quality = [c for c in codes if taxonomy.REASONS[c].category == "QUALITY"]

    if args.clear:
        with store._db() as db:
            db.execute("DELETE FROM returns WHERE source = 'demo'")

    now = datetime.now(timezone.utc)
    meta = {"taxonomy_version": taxonomy.TAXONOMY_VERSION, "prompt_hash": "demo"}
    for _ in range(args.rows):
        sku, vendor = rng.choice(CATALOGUE)
        roll = rng.random()
        if sku == HOT_FIT_SKU and roll < 0.55:
            code = rng.choice([c for c in fit if c in ("SIZE_TOO_SMALL", "TIGHT_AT_CHEST", "SIZE_CHART_MISLEADING")] or fit)
        elif sku == HOT_QUALITY_SKU and roll < 0.5:
            code = "STITCHING_CAME_APART" if "STITCHING_CAME_APART" in texts else rng.choice(quality)
        else:
            code = rng.choice(codes)
        when = now - timedelta(days=rng.uniform(0, args.days - 0.1))
        store.save_result(
            {"mode": "text", "text": rng.choice(texts[code]), "detected_language": None},
            fake_result(code), {"total_inr": 0.08}, meta, sku, vendor, origin="demo",
            created_at=when.isoformat(timespec="seconds"))
    print(f"Wrote {args.rows} synthetic returns to {store.DB_PATH}. "
          f"See them at /api/returns/digest?source=demo")


if __name__ == "__main__":
    main()
