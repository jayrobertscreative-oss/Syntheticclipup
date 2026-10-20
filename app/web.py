"""Server-rendered pages: public website + Phase 1 dashboard design previews.

The clipping engine's JSON API lives in app/main.py and is unchanged. Pages here never fake
platform numbers: live stats are read from the engine DB, illustrative content is labelled.
"""
from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from . import config, db, demo, fees

templates = Jinja2Templates(directory=str(config.ROOT / "app" / "templates"))
templates.env.globals.update(money=fees.fmt_money)
templates.env.filters["money"] = fees.fmt_money
templates.env.filters["compact"] = lambda n: (f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.1f}K" if n >= 1e4 else f"{n:,}") if n is not None else "—"

PUBLIC_NAV = [("/", "Home"), ("/campaigns", "Explore Campaigns"), ("/clip-studio", "Clip Studio"),
              ("/portfolio-builder", "Portfolio Builder"), ("/how-it-works", "How It Works"), ("/pricing", "Pricing")]


def previews_enabled() -> bool:
    return os.environ.get("SCU_DESIGN_PREVIEWS", "1") != "0"


def render(request: Request, name: str, **ctx):
    ctx.setdefault("nav", PUBLIC_NAV)
    ctx.setdefault("path", request.url.path)
    return templates.TemplateResponse(request, name, ctx)


# ---------- live, genuine numbers ----------

def live_stats() -> dict:
    conn = db.connect()
    try:
        clips = conn.execute("SELECT COUNT(*) FROM clips WHERE file_path IS NOT NULL").fetchone()[0]
        seconds = conn.execute("SELECT COALESCE(SUM(duration),0) FROM projects WHERE status='ready'").fetchone()[0]
    finally:
        conn.close()
    return {
        "clips": clips,
        "minutes": round(seconds / 60),
        # Marketplace tables arrive in Phase 2-3. Until then these are honestly zero.
        "campaigns_live": 0, "paid_out": 0,
    }


# ---------- public pages ----------

FAQ = [
    ("Do I need clients or followers to start?", "No. Join open campaigns, make clips in Clip Studio, post them on your own verified accounts and get paid on eligible views. Your portfolio grows with every accepted clip."),
    ("Why must I submit within 60 minutes of posting?", "It proves the clip is fresh and yours. We check the publish time and account through official platform APIs where they allow it. Where they don't, the submission goes to Verification Pending for a manual check rather than being auto-approved."),
    ("What does “Pay As You Go — Rewards Not Pre-Funded” mean?", "The host has paid a launch fee and set a spending limit, but hasn't deposited the reward budget. Rewards are paid as the host funds approved clips. Fully Funded campaigns have deposited the whole budget, and only show that badge once the payment has settled."),
    ("What does Synthetic Clip Up charge?", "Hosts pay a 10% platform fee. Clippers pay 5% of rewards when they're paid out. Every fee is shown before you commit, and the maths is done on our servers."),
    ("How is a campaign manager verified?", "After paying at least $2,000 to clippers through the platform (excluding fees, refunds and reversals), passing risk checks and owner approval. The tick means verified payout history here."),
    ("Does Clip Studio download videos from YouTube?", "No. YouTube's official API gives details about a video, not the file. Upload your original or a video you have permission to use. Clip Studio processes it for real: transcription, highlight picks, captions and rendering."),
    ("Do you hold money in escrow?", "No — we don't describe or operate the platform as escrow. Payments run through an approved marketplace payment provider. Payment terms will be published before real-money campaigns open."),
]


async def home(request: Request):
    s = fees.FeeSettings.from_env()
    return render(request, "public/home.html", stats=live_stats(), campaigns=demo.EXAMPLE_CAMPAIGNS[:3], faq=FAQ,
                  funded=fees.quote_funded(1_000_000, s), flex=fees.quote_flexible(1_000_000, s), s=s, payout=fees.clipper_payout(10_000, s),
                  hero=fees.reward_breakdown(184_200, demo.EXAMPLE_CAMPAIGNS[0]["rate_per_1k"], s=s))


async def campaigns(request: Request):
    return render(request, "public/campaigns.html", campaigns=demo.EXAMPLE_CAMPAIGNS, categories=demo.CATEGORIES,
                  platforms=list(demo.PLATFORMS.values()), stats=live_stats())


async def clip_studio(request: Request):
    return render(request, "public/clip_studio.html", stats=live_stats(), styles=["Creator Bold", "Purple Pulse", "Gaming Energy", "Podcast Clean", "Minimal", "Cinematic"])


async def portfolio_builder(request: Request):
    return render(request, "public/portfolio_builder.html", pf=demo.PORTFOLIO)


async def how_it_works(request: Request):
    return render(request, "public/how_it_works.html", faq=FAQ, statuses=demo.SUBMISSION_STATUSES)


async def pricing(request: Request):
    s = fees.FeeSettings.from_env()
    return render(request, "public/pricing.html", s=s, funded=fees.quote_funded(1_000_000, s), flex=fees.quote_flexible(1_000_000, s),
                  payout=fees.clipper_payout(10_000, s), faq=FAQ[2:5])


async def sign_in(request: Request):
    return render(request, "public/sign_in.html")


async def get_started(request: Request):
    role = request.query_params.get("role", "clipper")
    return render(request, "public/get_started.html", role=role if role in ("clipper", "manager") else "clipper")


async def legal(request: Request):
    return render(request, "public/legal.html")


async def fee_quote(request: Request):
    """Server-side fee maths for the pricing calculator and campaign form. Display only; no money moves."""
    q = request.query_params
    s = fees.FeeSettings.from_env()
    try:
        mode = q.get("mode", "funded")
        if mode == "funded":
            data = fees.quote_funded(fees.parse_major(q.get("budget", "0")), s)
        elif mode == "flexible":
            data = fees.quote_flexible(fees.parse_major(q.get("budget", "0")), s)
        elif mode == "reward":
            views = int(q.get("views", "0"))
            if not 0 <= views <= 10_000_000_000:
                raise ValueError("Views must be between 0 and 10 billion")
            cap = q.get("cap")
            data = fees.reward_breakdown(views, fees.parse_major(q.get("rate", "0")),
                                         min_views=int(q.get("min_views", "0") or 0),
                                         max_payout_minor=fees.parse_major(cap) if cap else None, s=s)
        else:
            return JSONResponse({"error": "mode must be funded, flexible or reward"}, status_code=400)
    except (ValueError, TypeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    data["formatted"] = {k: fees.fmt_money(v) for k, v in data.items()
                         if isinstance(v, int) and not isinstance(v, bool) and k not in ("host_fee_bps", "clipper_fee_bps", "eligible_views")}
    return JSONResponse(data)


# ---------- dashboard design previews ----------

ROLE_META = {
    "clipper": ("Clipper", "Kai Morgan"),
    "manager": ("Campaign Manager", "Ledger & Co."),
    "owner": ("Owner Control Centre", "Platform owner"),
}

# (group, [(slug, label, icon, count)])
NAVS = {
    "clipper": [
        ("", [("overview", "Overview", "home", None)]),
        ("Campaigns", [("recommended", "Recommended", "star", None), ("joined", "Joined campaigns", "flag", None), ("invitations", "Invitations", "chat", 2)]),
        ("Clips", [("submit", "Submit a clip", "upload", None), ("submissions", "Submissions", "list", None), ("studio", "Clip Studio", "scissors", None), ("library", "Content library", "folder", None)]),
        ("Earnings", [("earnings", "Earnings", "wallet", None), ("payouts", "Payouts & history", "card", None)]),
        ("Growth", [("accounts", "Connected accounts", "link", None), ("portfolio", "Portfolio builder", "layout", None), ("site-analytics", "Website analytics", "chart", None), ("enquiries", "Client enquiries", "inbox", 2)]),
        ("Account", [("notifications", "Notifications", "bell", None), ("settings", "Settings", "settings", None)]),
    ],
    "manager": [
        ("", [("overview", "Overview", "home", None)]),
        ("Campaigns", [("create", "Create campaign", "plus", None), ("manage", "Manage campaigns", "flag", None), ("funding", "Funding", "wallet", None)]),
        ("Review", [("review", "Pending review", "clock", 3), ("accepted", "Accepted clips", "check", None), ("rejected", "Rejected clips", "x", None), ("analytics", "Campaign analytics", "chart", None)]),
        ("Payouts", [("rewards", "Reward distribution", "dollar", None), ("payout-history", "Payout history", "card", None)]),
        ("Community", [("invitations", "Invitations & links", "chat", None), ("clippers", "Clippers", "users", None)]),
        ("Account", [("verification", "Verification", "shield", None), ("billing", "Billing", "card", None), ("settings", "Settings", "settings", None)]),
    ],
    "owner": [
        ("", [("overview", "Control centre", "home", None)]),
        ("Finance", [("revenue", "Revenue", "chart", None), ("owner-payouts", "Owner payouts", "wallet", None), ("statements", "Statements & exports", "folder", None)]),
        ("Marketplace", [("campaigns", "Campaign oversight", "flag", None), ("leaderboard", "Clipper leaderboard", "trophy", None), ("disputes", "Disputes & escalations", "alert", 4)]),
        ("Accounts", [("accounts", "Account search", "search", None), ("verifications", "Verification approvals", "shield", 2), ("audit", "Activity & audit log", "list", None)]),
        ("Platform", [("fees", "Fee settings", "dollar", None), ("categories", "Categories", "grid", None), ("platform-analytics", "Platform analytics", "chart", None)]),
    ],
}

BUILT = {"clipper": {"overview", "submit", "accounts", "portfolio"}, "manager": {"overview", "create", "review"}, "owner": {"overview"}}

# What each not-yet-designed screen will contain, and the phase that delivers it.
PLANNED = {
    ("clipper", "recommended"): (3, ["Campaigns matched to your connected platforms and categories", "Funding badge and reward rate on every card", "One-tap join for eligible campaigns"]),
    ("clipper", "joined"): (3, ["Requirements, hashtags, captions and mentions per campaign", "Host community link — or “not provided by host”", "Announcements; reward changes apply to future submissions only"]),
    ("clipper", "invitations"): (3, ["Discord, group-chat and community links from hosts you joined", "Revoked links disappear automatically", "Opt-in alerts for new campaigns from the same hosts"]),
    ("clipper", "submissions"): (5, ["Every submission with its full status history", "Verification evidence per check (identity, time window, duplicate)", "Open a dispute on rejected clips"]),
    ("clipper", "studio"): (10, ["The existing Clip Studio, now tied to your account", "Subtitle editing and trimming after render", "“Use in campaign” hand-off to Submit a clip"]),
    ("clipper", "library"): (10, ["All rendered clips and exports", "Filters by project, aspect ratio and campaign use"]),
    ("clipper", "earnings"): (8, ["Gross, 5% platform fee and net for every reward", "Per-campaign and per-platform breakdowns", "Transparent CPM calculation per clip"]),
    ("clipper", "payouts"): (7, ["Payout account via Stripe Connect", "Available vs pending balance", "Payment history with downloadable statements"]),
    ("clipper", "site-analytics"): (11, ["Portfolio visits, sources and enquiry conversion"]),
    ("clipper", "enquiries"): (12, ["Inbox for Hire Me / Work With Me enquiries", "Status tracking and agreed project details", "No marketplace fee on off-platform retainers"]),
    ("clipper", "notifications"): (14, ["In-app feed and email preferences per event type"]),
    ("clipper", "settings"): (2, ["Profile, password, sessions, data export and deletion"]),
    ("manager", "manage"): (3, ["All campaigns with status, funding and budget use", "Pause new submissions; edit for future submissions only"]),
    ("manager", "funding"): (7, ["Add funds, view settlement status, launch-fee credit balance", "Authorised spending limit for Pay As You Go campaigns"]),
    ("manager", "accepted"): (6, ["Accepted clips with live view snapshots and reward status"]),
    ("manager", "rejected"): (6, ["Rejected clips with reasons and any open disputes"]),
    ("manager", "analytics"): (8, ["Verified views over time, cost per 1K views, top clippers and platforms"]),
    ("manager", "rewards"): (7, ["Reward obligations awaiting funding", "Pay individually or in batches, with payment deadlines"]),
    ("manager", "payout-history"): (7, ["Every transfer to clippers, refunds and statements"]),
    ("manager", "invitations"): (3, ["Add, update and revoke Discord / group-chat / community links", "Post announcements to participants"]),
    ("manager", "clippers"): (3, ["Participants, their performance and acceptance rate"]),
    ("manager", "verification"): (9, ["Qualifying payouts toward $2,000", "What counts and what is excluded", "Review status once the threshold is reached"]),
    ("manager", "billing"): (7, ["Saved payment methods, invoices, fee receipts"]),
    ("manager", "settings"): (2, ["Team profile, brand details, notifications"]),
    ("owner", "revenue"): (13, ["Revenue by fee type, daily/weekly/monthly, with date filter and export"]),
    ("owner", "owner-payouts"): (13, ["Connect business payout account", "Withdraw only from platform-fee ledger balance — never reward funds"]),
    ("owner", "statements"): (13, ["Financial statements and transaction exports (CSV)"]),
    ("owner", "campaigns"): (13, ["Every campaign; sort by budget, revenue, views, submissions, acceptance, payouts", "Inspect, suspend, reinstate"]),
    ("owner", "leaderboard"): (13, ["Top clippers by verified views, earnings, approvals; 7/30/90/all-time"]),
    ("owner", "disputes"): (6, ["Escalated reviews past 72 h, disputes, independent decisions"]),
    ("owner", "accounts"): (13, ["Search all accounts; suspend, reinstate; payment histories"]),
    ("owner", "verifications"): (9, ["Approve or revoke manager verification and manual social verifications"]),
    ("owner", "audit"): (13, ["Every admin action and sensitive change, with actor and before/after"]),
    ("owner", "fees"): (7, ["Global, per-manager and per-campaign fee rates and promotions", "Launch-fee minimum and maximum"]),
    ("owner", "categories"): (3, ["Add, rename and retire campaign categories"]),
    ("owner", "platform-analytics"): (13, ["Registrations, active clippers/hosts, verified views, payment failures"]),
}


def _line_chart(points: list[tuple[str, int]], w=640, h=200, pad=(12, 8, 26, 44)) -> dict:
    top, right, bottom, left = pad
    vals = [v for _, v in points]
    vmax = max(vals) * 1.1 or 1
    step = 5_000 if vmax < 40_000 else 10_000
    vmax = (int(vmax // step) + 1) * step
    iw, ih = w - left - right, h - top - bottom
    xs = [left + i * iw / (len(points) - 1) for i in range(len(points))]
    ys = [top + ih - v / vmax * ih for v in vals]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    area = path + f" L{xs[-1]:.1f},{top + ih:.1f} L{xs[0]:.1f},{top + ih:.1f} Z"
    ticks = [(top + ih - t / vmax * ih, fees.fmt_money(t)) for t in range(0, vmax + 1, step * (2 if vmax / step > 6 else 1))]
    return {"w": w, "h": h, "path": path, "area": area, "ticks": ticks, "left": left, "right": w - right, "base": top + ih,
            "pts": [{"x": x, "y": y, "label": lab, "value": fees.fmt_money(v)} for x, y, (lab, v) in zip(xs, ys, points)],
            "band": iw / (len(points) - 1)}


def _stacked_bars(labels, series, w=680, h=220, pad=(12, 8, 26, 48)) -> dict:
    top, right, bottom, left = pad
    totals = [sum(r) for r in series]
    step = 20_000
    vmax = (int(max(totals) * 1.08 // step) + 1) * step
    iw, ih = w - left - right, h - top - bottom
    bw_full = iw / len(labels)
    bw = min(28, bw_full * 0.62)
    bars = []
    for i, (lab, row) in enumerate(zip(labels, series)):
        x = left + i * bw_full + (bw_full - bw) / 2
        y = top + ih
        segs = []
        for k, v in enumerate(row):
            if not v:
                continue
            hgt = v / vmax * ih
            y -= hgt
            segs.append({"y": y + 1, "h": max(0, hgt - 2), "k": k})  # 2px surface gap between segments
        bars.append({"x": x, "w": bw, "label": lab, "short": lab.split()[-1], "segs": segs,
                     "tip": [fees.fmt_money(v) for v in row], "total": fees.fmt_money(sum(row)), "cx": x + bw / 2})
    ticks = [(top + ih - t / vmax * ih, fees.fmt_money(t)) for t in range(0, vmax + 1, step * 2)]
    return {"w": w, "h": h, "bars": bars, "ticks": ticks, "left": left, "right": w - right, "base": top + ih, "band": bw_full}


def _dash(request: Request, role: str, screen: str, template: str, **ctx):
    label, who = ROLE_META[role]
    return render(request, template, role=role, role_label=label, who=who, screen=screen, side=NAVS[role],
                  built=BUILT[role], **ctx)


async def design_index(request: Request):
    if not previews_enabled():
        return HTMLResponse("Not found", status_code=404)
    return render(request, "design/index.html", roles=ROLE_META, built=BUILT, navs=NAVS)


async def design_screen(request: Request):
    if not previews_enabled():
        return HTMLResponse("Not found", status_code=404)
    role, screen = request.path_params["role"], request.path_params.get("screen", "overview")
    if role not in NAVS:
        return HTMLResponse("Not found", status_code=404)
    if role == "clipper" and screen == "overview":
        d = demo.clipper_overview()
        return _dash(request, role, screen, "design/clipper_overview.html", d=d, chart=_line_chart(d["earnings"]))
    if role == "clipper" and screen == "submit":
        return _dash(request, role, screen, "design/clipper_submit.html", d=demo.clipper_overview(), statuses=demo.SUBMISSION_STATUSES)
    if role == "clipper" and screen == "accounts":
        return _dash(request, role, screen, "design/clipper_accounts.html", accounts=demo.CONNECTED_ACCOUNTS)
    if role == "clipper" and screen == "portfolio":
        return _dash(request, role, screen, "design/portfolio_editor.html", pf=demo.PORTFOLIO)
    if role == "manager" and screen == "overview":
        return _dash(request, role, screen, "design/manager_overview.html", d=demo.manager_overview())
    if role == "manager" and screen == "create":
        return _dash(request, role, screen, "design/manager_create.html", categories=demo.CATEGORIES,
                     platforms=list(demo.PLATFORMS.values()), s=fees.FeeSettings.from_env())
    if role == "manager" and screen == "review":
        return _dash(request, role, screen, "design/manager_review.html", queue=demo.REVIEW_QUEUE)
    if role == "owner" and screen == "overview":
        d = demo.owner_overview()
        return _dash(request, role, screen, "design/owner_overview.html", d=d, chart=_stacked_bars(d["days"], d["series"]))
    for _, items in NAVS[role]:
        for slug, lab, icon, _c in items:
            if slug == screen:
                phase, bullets = PLANNED.get((role, screen), (None, []))
                return _dash(request, role, screen, "design/planned.html", title=lab, phase=phase, bullets=bullets)
    return HTMLResponse("Not found", status_code=404)


async def design_portfolio_public(request: Request):
    if not previews_enabled():
        return HTMLResponse("Not found", status_code=404)
    return render(request, "design/portfolio_public.html", pf=demo.PORTFOLIO)


routes = [
    Route("/", home),
    Route("/campaigns", campaigns),
    Route("/clip-studio", clip_studio),
    Route("/portfolio-builder", portfolio_builder),
    Route("/how-it-works", how_it_works),
    Route("/pricing", pricing),
    Route("/sign-in", sign_in),
    Route("/get-started", get_started),
    Route("/legal", legal),
    Route("/api/fees/quote", fee_quote),
    Route("/design", design_index),
    Route("/design/u/demo", design_portfolio_public),
    Route("/design/{role}", design_screen),
    Route("/design/{role}/{screen}", design_screen),
]
