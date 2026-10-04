"""Return-reason taxonomy: the ONE place reasons are defined.

This is the team's list of 61 reasons, grouped by who at Dhaga & Co. acts on
each. `ref` is the team's reason number. The one-line hints tell the model
where the line sits between similar reasons; they were drafted with the code
and should be reviewed by the team.

To change the list, edit CATEGORIES and EXAMPLES here and bump TAXONOMY_VERSION.
The prompt, the reply schema, the validation, the owner routing and the API
responses are all generated from this file.
"""

from dataclasses import dataclass

# Stored with every result so a label can be traced to the list that produced it.
TAXONOMY_VERSION = "team-61-2026-10-03b"

# Reasons in this category are never accepted as "Classified"; they always mean Needs Review.
UNCLEAR_CATEGORY = "UNCLEAR"
# Used when the model is not confident enough in any reason.
UNCLEAR_CODE = "UNCLEAR_FREE_TEXT"


@dataclass(frozen=True)
class Reason:
    code: str
    label: str
    category: str        # category code
    category_label: str
    owner: str           # who the finding is routed to (lookup in code, not a model decision)
    hint: str = ""       # one line telling the model when to use this reason
    ref: int | None = None  # the team's reason number


# category code -> (category label, owner, [(reason code, label, hint, ref), ...])
CATEGORIES = {
    "FIT": ("Fit and size", "Neha (catalogue, size charts)", [
        ("SIZE_TOO_SMALL", "Size too small", "Small or tight overall, or at a body area with no specific reason below. The size received is the size ordered.", 1),
        ("SIZE_TOO_LARGE", "Size too large", "Big or loose overall, or at a body area with no specific reason below. The size received is the size ordered.", 2),
        ("LENGTH_TOO_SHORT", "Length too short", "Garment length (not sleeves) is shorter than wanted.", 3),
        ("LENGTH_TOO_LONG", "Length too long", "Garment length (not sleeves) is longer than wanted.", 4),
        ("TIGHT_AT_CHEST", "Tight at chest", "Tight specifically at the chest or bust. Loose at the chest is SIZE_TOO_LARGE.", 5),
        ("LOOSE_AT_WAIST", "Loose at waist", "Loose specifically at the waist. Tight at the waist is SIZE_TOO_SMALL.", 6),
        ("SLEEVES_TOO_LONG", "Sleeves too long", "", 7),
        ("SLEEVES_TOO_SHORT", "Sleeves too short", "", 8),
        ("KIDS_SIZE_MISMATCH", "Kids size mismatch", "A child's garment bought by age (e.g. 'six to seven years') fits like a different age, bigger or smaller. Use this whenever the size is given as an age.", 9),
        ("SIZE_CHART_MISLEADING", "Size chart misleading", "Customer mentions the size chart or the listed measurements and says the product does not match them, even if they also say tight or loose.", 10),
        ("FIT_UNLIKE_PHOTOS", "Fit unlike photos", "The cut or silhouette differs from the photos (e.g. loose in the photo, fitted in reality).", 11),
    ]),
    "QUALITY": ("Product quality", "Vendor QC (Tiruppur, Jaipur)", [
        ("STITCHING_CAME_APART", "Stitching came apart", "Seams, hems or stitching opening.", 12),
        ("FABRIC_FEELS_CHEAP", "Fabric feels cheap", "Fabric is thin, rough or poor quality. No claim that the listing named a different fabric.", 13),
        ("FABRIC_IS_TRANSPARENT", "Fabric is transparent", "See-through fabric or missing lining.", 14),
        ("BLEEDS_WHEN_WASHED", "Bleeds when washed", "Colour runs or stains other clothes in the wash.", 15),
        ("SHRUNK_AFTER_WASHING", "Shrunk after washing", "Fitted before washing, smaller after.", 16),
        ("PRINT_FADED_QUICKLY", "Print faded quickly", "Print or colour faded with wear or washing, without running onto other clothes.", 17),
        ("ZIP_NOT_WORKING", "Zip not working", "", 18),
        ("BUTTONS_FELL_OFF", "Buttons fell off", "Buttons or hooks loose, missing or broken.", 19),
        ("LOOSE_THREADS_EVERYWHERE", "Loose threads everywhere", "Untrimmed threads, but seams are intact.", 20),
        ("STAIN_ON_GARMENT", "Stain on garment", "Stain or mark on the garment when it arrived.", 21),
        ("TORN_ON_ARRIVAL", "Torn on arrival", "Garment torn or has a hole when unpacked, with no sign the parcel itself was damaged.", 22),
        ("STRONG_CHEMICAL_SMELL", "Strong chemical smell", "", 23),
        ("EMBROIDERY_CAME_OFF", "Embroidery came off", "Embroidery, sequins, beads or lace coming off.", 24),
        ("PILLING_AFTER_WEAR", "Pilling after wear", "Bobbles or fuzz on the fabric after wearing.", 25),
        ("ELASTIC_LOST_STRETCH", "Elastic lost stretch", "Elastic became loose after use. If it was loose from the start, that is a fit reason.", 26),
    ]),
    "NOT_AS_DESCRIBED": ("Not as described", "Vivek (listing team, product copy)", [
        ("COLOUR_NOT_MATCHING", "Colour not matching", "Shade differs from the photos, but it is the colour variant that was ordered.", 27),
        ("DIFFERENT_FROM_PICTURES", "Different from pictures", "Looks different from the photos in a way no other reason here covers.", 28),
        ("FABRIC_UNLIKE_DESCRIPTION", "Fabric unlike description", "The listing named one fabric and the product is another (e.g. cotton written, polyester received).", 29),
        ("PRINT_UNLIKE_PHOTOS", "Print unlike photos", "Print or pattern differs from the photos.", 30),
        ("DESIGN_NOT_MATCHING", "Design not matching", "Neckline, sleeves style, cut details or other design features differ from the listing.", 31),
        ("EMBELLISHMENT_LOOKS_CHEAP", "Embellishment looks cheap", "Embroidery or work looks poorer than in the photos (not coming off).", 32),
        ("DUPATTA_NOT_INCLUDED", "Dupatta not included", "Customer expected a dupatta from the photos or listing and the product does not come with one.", 33),
    ]),
    "FULFILMENT": ("Fulfilment error", "Warehouse (Unicommerce, three FCs)", [
        ("WRONG_ITEM_SENT", "Wrong item sent", "A different product type or design from the one ordered (ordered a kurti, got a saree), even if the colour is also different.", 34),
        ("WRONG_SIZE_SENT", "Wrong size sent", "The size printed on the tag or packet is different from the size ordered. If the tag shows the ordered size but it measures small or large, that is a fit reason.", 35),
        ("WRONG_COLOUR_SENT", "Wrong colour sent", "The right product in a different colour variant (ordered blue, got red).", 36),
        ("INCOMPLETE_SET_RECEIVED", "Incomplete set received", "A piece of the set or of the order is missing from the parcel.", 37),
        ("DUPLICATE_ITEM_RECEIVED", "Duplicate item received", "Received more pieces than ordered.", 38),
        ("RECEIVED_USED_PRODUCT", "Received used product", "Product looks worn, washed or previously returned.", 39),
        ("PACKAGE_WAS_TAMPERED", "Package was tampered", "Parcel was opened or resealed before delivery.", 40),
        ("EMPTY_PACKAGE_RECEIVED", "Empty package received", "", 41),
    ]),
    "DELIVERY": ("Delivery", "Faizan (Delhivery, Shiprocket, Ekart)", [
        ("DELIVERED_TOO_LATE", "Delivered too late", "Arrived later than promised or expected, with no specific event mentioned.", 42),
        ("OCCASION_ALREADY_PASSED", "Occasion already passed", "Bought for a wedding, festival or event that was over by the time it arrived.", 43),
        ("DAMAGED_IN_TRANSIT", "Damaged in transit", "Parcel was crushed or torn in shipping and the product was damaged with it.", 44),
        ("PACKAGE_ARRIVED_WET", "Package arrived wet", "", 45),
        ("DELIVERED_AFTER_CANCELLATION", "Delivered after cancellation", "Customer had cancelled and it was delivered anyway.", 46),
    ]),
    "CUSTOMER": ("Customer-side, no defect", "Arpita and Sameer (policy, not product)", [
        ("CHANGED_MY_MIND", "Changed my mind", "Customer says they changed their mind. NOT for a bare 'I don't like it' with no reason.", 47),
        ("ORDERED_BY_MISTAKE", "Ordered by mistake", "Customer ordered the wrong product or quantity, or placed the same order twice by accident.", 48),
        ("ORDERED_TWO_SIZES", "Ordered two sizes", "Customer deliberately ordered the same item in more than one size and is returning the extra. NOT when they ordered one size and now want a different size, and NOT for an accidental double order.", 49),
        ("FOUND_CHEAPER_ELSEWHERE", "Found cheaper elsewhere", "", 50),
        ("PRICE_DROPPED_LATER", "Price dropped later", "Price fell on Dhaga & Co. after the order.", 51),
        ("FAMILY_DIDNT_LIKE", "Family didn't like", "Bought for self; family or spouse disapproved.", 52),
        ("RECIPIENT_DIDNT_LIKE", "Recipient didn't like", "Bought as a gift or for someone else who did not like it.", 53),
        ("NO_LONGER_NEEDED", "No longer needed", "The need went away (plan cancelled, bought another) with no delivery delay blamed.", 54),
        ("WANTED_TO_TRY", "Wanted to try", "Ordered only to see or try it.", 55),
        ("EXCHANGE_SIZE_UNAVAILABLE", "Exchange size unavailable", "Wanted an exchange but the needed size is out of stock.", 56),
        ("COUPON_NOT_APPLIED", "Coupon not applied", "", 57),
        ("OVERCHARGED_ON_DELIVERY", "Overcharged on delivery", "Asked to pay more at delivery than the order amount.", 58),
    ]),
    UNCLEAR_CATEGORY: ("Unclassifiable", "Needs a human", [
        ("NO_REASON_GIVEN", "No reason given", "Only says they want to return, or nothing at all.", 59),
        ("MULTIPLE_REASONS_GIVEN", "Multiple reasons given", "The customer lists three or more separate problems. For exactly two problems use reason_code plus secondary_reason_code instead.", 60),
        ("UNCLEAR_FREE_TEXT", "Unclear free text", "Vague dislike with no reason ('bekaar', 'I don't like it'), unintelligible text, or anything that fits no reason above.", 61),
    ]),
}

# Worked examples shown to the model. Kept here so they change together with
# the reasons. Each is (customer text, reason code, secondary code or None).
# The first seven are the team's own examples, one per group.
EXAMPLES = [
    ("L mangwaya tha, M jaisa lag raha hai", "SIZE_TOO_SMALL", None),
    ("ek wash mein colour nikal gaya", "BLEEDS_WHEN_WASHED", None),
    ("photo mein toh alag hi colour tha", "COLOUR_NOT_MATCHING", None),
    ("kurti ki jagah top aa gaya", "WRONG_ITEM_SENT", None),
    ("shaadi nikal gayi, ab kya karun", "OCCASION_ALREADY_PASSED", None),
    ("do size mangwaye the, ek wapas", "ORDERED_TWO_SIZES", None),
    ("bekaar", UNCLEAR_CODE, None),
    ("The dress is too tight around my waist.", "SIZE_TOO_SMALL", None),
    ("Maine medium size order kiya tha lekin bahut loose hai.", "SIZE_TOO_LARGE", None),
    ("Size loose hai and stitching bhi open ho rahi hai.", "SIZE_TOO_LARGE", "STITCHING_CAME_APART"),
    ("I don't like it", UNCLEAR_CODE, None),
    ("return karna hai", "NO_REASON_GIVEN", None),
]


def _build() -> dict[str, Reason]:
    reasons: dict[str, Reason] = {}
    for cat, (cat_label, owner, items) in CATEGORIES.items():
        for code, label, hint, ref in items:
            if code in reasons:
                raise ValueError(f"Duplicate reason code in taxonomy: {code}")
            reasons[code] = Reason(code, label, cat, cat_label, owner, hint, ref)
    if reasons.get(UNCLEAR_CODE) is None or reasons[UNCLEAR_CODE].category != UNCLEAR_CATEGORY:
        raise ValueError(f"{UNCLEAR_CODE} must exist in the {UNCLEAR_CATEGORY} category")
    refs = [r.ref for r in reasons.values() if r.ref is not None]
    if len(refs) != len(set(refs)):
        raise ValueError("Duplicate reason numbers (ref) in taxonomy")
    for text, code, secondary in EXAMPLES:
        for c in (code, secondary):
            if c is not None and c not in reasons:
                raise ValueError(f"Example {text!r} uses unknown reason code {c}")
    return reasons


REASONS: dict[str, Reason] = _build()  # fails at startup if the taxonomy is inconsistent
UNCLEAR_LABEL = CATEGORIES[UNCLEAR_CATEGORY][0]


def is_unclear(code: str) -> bool:
    return REASONS[code].category == UNCLEAR_CATEGORY


def prompt_block(reverse: bool = False) -> str:
    """The taxonomy as text for the model prompt. reverse=True lists it backwards,
    so a second, independent reading does not see the reasons in the same order."""
    lines = []
    order = (lambda seq: list(reversed(list(seq)))) if reverse else list
    for cat, (cat_label, _owner, items) in order(CATEGORIES.items()):
        lines.append(f"{cat_label}:")
        for code, label, hint, _ in order(items):
            lines.append(f"  {code} - {label}" + (f". {hint}" if hint else ""))
    return "\n".join(lines)


# What the customer sees on the category tiles. The team's own names (the ones in CATEGORIES)
# stay for the digest and the review queue; "Customer-side, no defect" is not something to say to a customer.
CUSTOMER_LABELS = {
    "FIT": "Size or fit",
    "QUALITY": "Quality problem",
    "NOT_AS_DESCRIBED": "Not like the photos or listing",
    "FULFILMENT": "Wrong or missing item",
    "DELIVERY": "Delivery problem",
    "CUSTOMER": "I changed my mind",
    UNCLEAR_CATEGORY: "Something else",
}


def as_menu() -> dict:
    """The two-level list for the screen: 7 first-level categories, reasons under each.
    Served by the API so the page never hardcodes a reason."""
    return {
        "version": TAXONOMY_VERSION,
        "categories": [
            {"code": cat, "label": cat_label, "customer_label": CUSTOMER_LABELS[cat], "owner": owner, "needs_review": cat == UNCLEAR_CATEGORY,
             "reasons": [{"code": code, "label": label} for code, label, _hint, _ref in items]}
            for cat, (cat_label, owner, items) in CATEGORIES.items()
        ],
    }
