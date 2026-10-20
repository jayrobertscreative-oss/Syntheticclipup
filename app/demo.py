"""Illustrative data for Phase 1 design previews ONLY.

Nothing in this module is ever shown without an "Example" or "Demo data" label, and nothing
here is read by the clipping engine, the API or (later) any financial code path. When the real
tables arrive (Phase 2+), each preview swaps its context for a query and this module shrinks.
Money values are minor units and pass through app.fees so the maths shown is the real maths.
"""
from __future__ import annotations

from . import fees

CATEGORIES = ["Gaming", "Streaming", "Finance", "Business", "Podcasts", "Lifestyle",
              "Entertainment", "Sports", "Education", "Technology", "Other"]
PLATFORMS = {"tiktok": ("TikTok", "TT"), "instagram": ("Instagram", "IG"), "youtube": ("YouTube", "YT"), "facebook": ("Facebook", "FB")}

# hue pairs for generated campaign artwork (no stock images, no third-party IP)
_ART = [(262, 198), (290, 220), (220, 170), (250, 320), (200, 260), (275, 190)]


def _campaign(i, title, host, verified, category, platforms, rate, budget, funding, spent=0, min_views=10_000, cap=None, joined=0):
    h1, h2 = _ART[i % len(_ART)]
    return {
        "id": f"ex-{i}", "title": title, "host": host, "host_verified": verified, "category": category,
        "platforms": [PLATFORMS[p] for p in platforms], "rate_per_1k": rate, "budget": budget,
        "funding": funding, "spent": spent, "remaining": budget - spent if funding == "funded" else None,
        "remaining_pct": round(100 * (budget - spent) / budget) if funding == "funded" else None,
        "min_views": min_views, "cap": cap, "participants": joined, "art": (h1, h2),
    }


EXAMPLE_CAMPAIGNS = [
    _campaign(0, "Late-night stream highlights", "Nova Streams", True, "Streaming", ["tiktok", "youtube"], 250, 800_000, "funded", 312_000, joined=86),
    _campaign(1, "Founder podcast — best moments", "Ledger & Co.", True, "Podcasts", ["tiktok", "instagram", "youtube"], 180, 500_000, "funded", 95_000, cap=30_000, joined=41),
    _campaign(2, "Speedrun world-record clips", "PixelPace", False, "Gaming", ["tiktok", "youtube"], 120, 1_000_000, "flexible", joined=129),
    _campaign(3, "Personal finance explainers", "Compound Club", True, "Finance", ["instagram", "youtube"], 300, 1_200_000, "funded", 600_000, min_views=25_000, joined=58),
    _campaign(4, "Product launch week", "Orbit Labs", False, "Technology", ["tiktok", "instagram", "facebook"], 150, 400_000, "flexible", joined=17),
    _campaign(5, "Matchday reactions", "Terrace Talk", False, "Sports", ["tiktok", "instagram"], 100, 250_000, "funded", 40_000, joined=33),
]

SUBMISSION_STATUSES = [
    ("draft", "Draft", "neutral"), ("verification_pending", "Verification Pending", "warn"),
    ("verification_failed", "Verification Failed", "err"), ("awaiting_review", "Awaiting Host Review", "info"),
    ("accepted", "Accepted", "ok"), ("rejected", "Rejected", "err"), ("disputed", "Disputed", "warn"),
    ("reward_pending", "Reward Pending", "brand"), ("payment_processing", "Payment Processing", "info"),
    ("paid", "Paid", "ok"),
]
STATUS = {k: (label, tone) for k, label, tone in SUBMISSION_STATUSES}


def _sub(title, campaign, platform, handle, status, views, rate, minutes_after, ago, min_views=10_000):
    b = fees.reward_breakdown(views, rate, min_views=min_views) if views is not None else None
    return {"title": title, "campaign": campaign, "platform": PLATFORMS[platform], "handle": handle,
            "status": status, "status_label": STATUS[status][0], "tone": STATUS[status][1],
            "views": views, "reward": b, "submitted_after_min": minutes_after, "ago": ago}


CLIPPER_SUBMISSIONS = [
    _sub("“Nobody saw that coming” — chat erupts", "Late-night stream highlights", "tiktok", "@kai.clips", "paid", 184_200, 250, 6, "3d ago"),
    _sub("Why compounding beats timing", "Personal finance explainers", "youtube", "Kai Clips", "payment_processing", 92_400, 300, 14, "2d ago", 25_000),
    _sub("Founder on the worst hire he made", "Founder podcast — best moments", "instagram", "@kai.clips", "awaiting_review", 31_050, 180, 22, "5h ago"),
    _sub("Any% skip explained in 40 seconds", "Speedrun world-record clips", "tiktok", "@kai.clips", "verification_pending", None, 120, 9, "48m ago"),
    _sub("Pre-match chant, row Z", "Matchday reactions", "instagram", "@kai.clips", "rejected", 4_100, 100, 71, "4d ago"),
]

CONNECTED_ACCOUNTS = [
    {"platform": PLATFORMS["tiktok"], "handle": "@kai.clips", "method": "OAuth", "state": "verified", "since": "Aug 2026", "followers": "48.2K", "health": "Healthy"},
    {"platform": PLATFORMS["youtube"], "handle": "Kai Clips", "method": "OAuth", "state": "verified", "since": "Aug 2026", "followers": "12.9K", "health": "Healthy"},
    {"platform": PLATFORMS["instagram"], "handle": "@kai.clips", "method": "Bio code", "state": "verified", "since": "Sep 2026", "followers": "21.4K", "health": "Token expires in 9 days"},
    {"platform": PLATFORMS["facebook"], "handle": "Kai Clips", "method": "Manual review", "state": "pending", "since": "Today", "followers": "—", "health": "Awaiting review"},
]

# 12 weeks of net earnings (minor units), single series
CLIPPER_EARNINGS = [("W" + str(i + 1), v) for i, v in enumerate(
    [4_200, 6_100, 5_400, 9_800, 8_700, 12_400, 15_100, 13_900, 18_600, 22_300, 19_800, 26_400])]


def clipper_overview() -> dict:
    paid = sum(s["reward"]["net"] for s in CLIPPER_SUBMISSIONS if s["status"] == "paid")
    pending = sum(s["reward"]["net"] for s in CLIPPER_SUBMISSIONS if s["status"] in ("payment_processing", "awaiting_review") and s["reward"])
    return {
        "name": "Kai", "balance": 42_850, "pending": pending, "paid_total": paid + 120_000,
        "views_30d": 1_284_000, "acceptance": 86, "active_campaigns": 4,
        "earnings": CLIPPER_EARNINGS, "submissions": CLIPPER_SUBMISSIONS, "accounts": CONNECTED_ACCOUNTS,
        "joined": [EXAMPLE_CAMPAIGNS[i] | {"community": c} for i, c in ((0, "Discord"), (1, None), (2, "Group chat"), (3, "Discord"))],
        "enquiries": [{"name": "Rowan Hale", "business": "Hale Fitness", "budget": "$500–1,000 / mo", "ago": "1h ago"},
                      {"name": "Priya N.", "business": "The Index Pod", "budget": "$1,000–2,500 / mo", "ago": "Yesterday"}],
    }


# ---------- campaign manager ----------

REVIEW_QUEUE = [
    {"clipper": "kai.clips", "platform": PLATFORMS["instagram"], "title": "Founder on the worst hire he made", "published": "14:02", "submitted": "14:24", "within": 22, "views": 31_050, "left_h": 61, "eligible": True},
    {"clipper": "mira.edits", "platform": PLATFORMS["tiktok"], "title": "The pricing mistake that cost £40k", "published": "11:47", "submitted": "11:58", "within": 11, "views": 58_900, "left_h": 22, "eligible": True},
    {"clipper": "jj_cuts", "platform": PLATFORMS["youtube"], "title": "Hiring for attitude, not CV", "published": "09:10", "submitted": "09:51", "within": 41, "views": 7_300, "left_h": 5, "eligible": False},
]


def manager_overview() -> dict:
    camps = [EXAMPLE_CAMPAIGNS[1], EXAMPLE_CAMPAIGNS[4]]
    return {
        "name": "Ledger & Co.", "funded_balance": 405_000, "obligations": 61_870, "pending_reviews": len(REVIEW_QUEUE),
        "views_30d": 2_940_000, "spend_30d": 189_400, "campaigns": camps, "queue": REVIEW_QUEUE,
        "verification": fees.verification_progress(165_000),
        "funded_quote": fees.quote_funded(500_000), "flex_quote": fees.quote_flexible(400_000),
    }


# ---------- owner ----------

OWNER_REVENUE_DAYS = ["Oct " + str(d) for d in range(7, 21)]
# per-day revenue by fee type (minor units): host launch fees, host transaction fees, clipper fees
OWNER_REVENUE = [
    (40_000, 21_000, 9_800), (0, 18_400, 8_100), (25_000, 26_000, 11_300), (0, 30_100, 12_900),
    (60_000, 24_800, 10_200), (0, 12_300, 6_000), (0, 9_900, 5_100), (35_000, 28_700, 12_600),
    (0, 33_400, 14_300), (80_000, 31_200, 13_800), (0, 36_900, 15_500), (20_000, 40_100, 17_200),
    (0, 22_600, 9_700), (45_000, 38_300, 16_400),
]


def owner_overview() -> dict:
    launch = sum(r[0] for r in OWNER_REVENUE)
    tx = sum(r[1] for r in OWNER_REVENUE)
    clip = sum(r[2] for r in OWNER_REVENUE)
    gross_rev = launch + tx + clip
    refunds, chargebacks, processing = 18_500, 4_200, 61_300
    net = gross_rev - refunds - chargebacks - processing
    return {
        "launch": launch, "tx": tx, "clip": clip, "gross_rev": gross_rev, "refunds": refunds,
        "chargebacks": chargebacks, "processing": processing, "net": net,
        "volume": 6_412_000, "payouts": 4_870_500, "owner_available": net - 150_000, "owner_paid": 150_000,
        "pending_withdrawals": 0, "reserved": 1_284_000,
        "days": OWNER_REVENUE_DAYS, "series": OWNER_REVENUE,
        "campaigns": [c | {"revenue": fees.quote_funded(c["budget"])["host_fee"] if c["funding"] == "funded" else fees.launch_fee(c["budget"]),
                           "views": v, "subs": n, "accept": a}
                      for c, v, n, a in zip(EXAMPLE_CAMPAIGNS, [4_120_000, 1_830_000, 2_640_000, 3_010_000, 410_000, 980_000],
                                            [312, 144, 401, 220, 39, 97], [81, 77, 64, 88, 72, 69])],
        "leaders": [
            {"handle": "mira.edits", "views": 3_920_000, "earned": 612_400, "clips": 88, "accept": 91},
            {"handle": "kai.clips", "views": 2_610_000, "earned": 401_900, "clips": 64, "accept": 86},
            {"handle": "northcut", "views": 2_180_000, "earned": 355_300, "clips": 71, "accept": 79},
            {"handle": "jj_cuts", "views": 1_440_000, "earned": 198_700, "clips": 52, "accept": 70},
            {"handle": "studio.vee", "views": 1_120_000, "earned": 171_000, "clips": 33, "accept": 94},
        ],
        "approvals": [
            {"what": "Manager verification", "who": "Compound Club", "detail": "$2,140 qualifying payouts · risk checks passed"},
            {"what": "Social account (manual)", "who": "kai.clips · Facebook", "detail": "Bio code unavailable · screenshot evidence"},
            {"what": "Escalated review", "who": "Speedrun world-record clips", "detail": "7 submissions past 72 h"},
            {"what": "Dispute", "who": "jj_cuts vs Terrace Talk", "detail": "Rejected for wrong hashtag · clipper disputes"},
        ],
    }


PORTFOLIO = {
    "name": "Kai Morgan", "handle": "kai", "headline": "Short-form editor for podcasts & streams",
    "bio": "I turn long conversations into clips people finish. 60+ campaigns, verified accounts on three platforms.",
    "metrics": [("Verified views", "8.4M"), ("Campaigns completed", "63"), ("Avg. views per clip", "41K")],
    "accounts": CONNECTED_ACCOUNTS[:3],
}
