"""Demo orders for the returns screen.

There is no orders feed in this MVP (the real one is eleven million rows in Postgres), so three
hand-made orders stand in for it. Each has 2-3 items; the customer picks the one to return.
Prices sit in the brief's range (Rs 399 to 1,499); SKU codes and vendor names are placeholders.

What each order is for (the screen never says this; it is the demo script, see README):
  DH-24101  positive: one clear Hinglish reason, auto-accepted
  DH-24102  positive: two problems at once (size + stitching), two owners
  DH-24103  failure shown on purpose: "too tight around my waist" is read as LOOSE_AT_WAIST at 1.0
            confidence; the direction check in returns.py catches it and asks the customer to confirm
"""

CUSTOMER = {"name": "Priya"}

ORDERS = [
    {
        "id": "DH-24101", "placed": "2026-09-24", "delivered": "2026-09-29",
        "payment": "Cash on delivery", "carrier": "Delhivery", "total": 1447,
        "items": [
            {"sku": "DH-KRT-0412", "name": "Cotton kurti, mustard", "size": "M", "price": 599,
             "vendor": "Jaipur V12", "emoji": "👗", "tint": "#e0a526"},
            {"sku": "DH-PLZ-0233", "name": "Straight palazzo, black", "size": "M", "price": 449,
             "vendor": "Jaipur V12", "emoji": "👖", "tint": "#3a3f55"},
            {"sku": "DH-DUP-0087", "name": "Printed dupatta, rust", "size": "Free", "price": 399,
             "vendor": "Jaipur V15", "emoji": "🧣", "tint": "#b5532c"},
        ],
    },
    {
        "id": "DH-24102", "placed": "2026-09-26", "delivered": "2026-10-01",
        "payment": "Paid online", "carrier": "Shiprocket", "total": 2498,
        "items": [
            {"sku": "DH-MXD-0651", "name": "Floral maxi dress", "size": "L", "price": 1199,
             "vendor": "Tiruppur V07", "emoji": "👗", "tint": "#c25a7c"},
            {"sku": "DH-COS-0318", "name": "Linen co-ord set, sage", "size": "M", "price": 1299,
             "vendor": "Jaipur V09", "emoji": "👚", "tint": "#7d9a79"},
        ],
    },
    {
        "id": "DH-24103", "placed": "2026-09-28", "delivered": "2026-10-03",
        "payment": "Paid online", "carrier": "Ekart", "total": 1797,
        "items": [
            {"sku": "DH-ALN-0540", "name": "A-line dress, navy", "size": "M", "price": 899,
             "vendor": "Tiruppur V03", "emoji": "👗", "tint": "#27348b"},
            {"sku": "DH-TOP-0129", "name": "Ribbed top, white", "size": "M", "price": 499,
             "vendor": "Tiruppur V03", "emoji": "👚", "tint": "#9aa3b8"},
            {"sku": "DH-LEG-0071", "name": "Cotton leggings, grey", "size": "M", "price": 399,
             "vendor": "Tiruppur V11", "emoji": "👖", "tint": "#6d7280"},
        ],
    },
]
