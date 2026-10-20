# Synthetic Clip Up — Design-First Implementation Plan

Status as of 20 Oct 2026. This plan answers the "First Deliverable" in the master brief and is the
reference for every later phase. Each feature below is tagged:

- **DONE** — built, tested in this repo.
- **PARTIAL** — some of it exists; the gap is named.
- **PLANNED** — not built yet; the phase that builds it is named.

Nothing here claims an integration works until a test in this repo proves it.

---

## 0. Architecture decision (read first)

The brief prefers Next.js + TypeScript + Tailwind + Supabase + Vercel **"if compatible with the existing
application"**. The existing application is a Python service:

- Starlette web/API (`app/main.py`), a background FFmpeg worker (`app/worker.py`), SQLite, Docker on Railway.
- The worker must run long FFmpeg jobs next to a persistent disk. That rules out Vercel/serverless for it
  (already noted in the README).

**Decision: one Python service for the whole platform, plus the existing worker.**

| Concern | Choice | Why |
|---|---|---|
| Web + API | Starlette (already in use) + Jinja2 server-rendered pages + small vanilla JS | One codebase, one deploy, shares the engine's DB and media storage. No Node build step. |
| Styling | Hand-written token-based CSS design system (`static/css/scu.css`) | Same tokens as the existing dashboard. Tailwind adds a build step without adding capability here. |
| Database | SQLite now → **PostgreSQL** from Phase 2 (Railway Postgres, or Supabase Postgres) | `app/db.py` was written to map 1:1 to Postgres. |
| Auth | Server-side sessions, Argon2 password hashing, TOTP MFA for owner (Phase 2) | Keeps secrets server-side; no third-party auth lock-in. Supabase Auth remains an option if you prefer it. |
| Payments | Stripe Connect (Express accounts for clippers) — **subject to Stripe approving the model** | See §10. |
| Hosting | Railway (already set up): web + worker in one container now, split into two services when load needs it | Avoids extra infrastructure. |

If you still want a Next.js front end later, the design tokens, page structure and API contracts in this
plan carry over unchanged; only the rendering layer would move.

---

## 1. Existing functionality to preserve

| Area | What exists | Status |
|---|---|---|
| Upload ingestion | Raw-body streaming upload, MP4/MOV magic-byte check, size limit, rights confirmation | DONE |
| Processing pipeline | 9 real stages: validate → prepare → extract audio → transcribe → analyse → generate → captions → render → completed | DONE |
| Transcription | OpenAI `whisper-1`, word timestamps, 20-min chunking | DONE (needs `OPENAI_API_KEY`) |
| Highlight selection | Claude tool-call picks + deterministic boundary snapping (`ai.finalize_clips`) | DONE (needs `ANTHROPIC_API_KEY`) |
| Captions | 6 burned-in ASS styles incl. Creator Bold / Purple Pulse | DONE |
| Exports | 9:16, 1:1, 16:9; crop or pad; thumbnails | DONE |
| Job queue | SQLite job table, atomic claim, heartbeat, stale-job requeue, retry endpoint | DONE |
| Private media | HMAC-signed, expiring media URLs with range requests; download counting | DONE |
| YouTube links | Official Data API v3 metadata only; refuses to scrape, tells users to upload originals | DONE |
| Dashboard | Vanilla-JS Clip Studio UI wired to the API | DONE — moved from `/` to `/studio` in Phase 1 |
| Branding | Neon "S" logo, emblem, favicon; tokens `#0B0B12 / #151521 / #1C1C2B / #7856FF / #36C8FF`; Sora / Inter / JetBrains Mono | DONE — reused verbatim |
| Tests | `tests/smoke_test.py` (real FFmpeg + HTTP, AI stubbed), `tests/live_check.py` | DONE — still passes |
| Clip Studio pricing (agreed earlier) | 200 free tokens per device, 25 tokens per AI clip, 20 per download; Clipper $20/mo (2,800 tokens), Clipper Premium $40/mo (unlimited), monthly, no cancellation fees | PLANNED — shown on the pricing page, billing in Phase 7 |

## 2. Missing functionality to build

Everything in the marketplace is new: accounts and roles, campaigns, joining, invitations, social
account connections and ownership verification, submissions with the 60-minute rule, host review,
payments and ledger, view tracking and reward calculation, manager verification, portfolio builder,
client enquiries, owner control centre, notifications. Clip Studio gaps: subtitle editing after
render, clip trimming UI, personal clip library tied to an account, export history per user, and
"authorised imports" beyond direct upload.

---

## 3. Public website structure

| Route | Page | Phase 1 status |
|---|---|---|
| `/` | Home: hero, Start Clipping / Launch a Campaign, how it works, featured campaigns, Clip Studio demo, portfolio showcase, verified-account benefits, analytics preview, fee transparency, FAQ, footer | DONE (examples labelled) |
| `/campaigns` | Explore Campaigns: search, filters, sort, campaign cards | DONE as UI; real listings Phase 3 |
| `/clip-studio` | Clip Studio product page → opens `/studio` | DONE |
| `/portfolio-builder` | Portfolio Builder product page | DONE |
| `/how-it-works` | Clipper and host flows, 60-min rule, funding types | DONE |
| `/pricing` | Fees, funding methods, live fee calculator (server-side maths), Clip Studio plans | DONE |
| `/sign-in`, `/get-started` | Auth screens; role choice is Clipper or Campaign Manager only | UI DONE; accounts Phase 2 |
| `/legal` | Terms, privacy, payout terms | Placeholder; must be written before any real-money launch |
| `/u/{username}` | Public clipper portfolio | Phase 11 (design preview exists) |
| `/studio` | Existing Clip Studio app | DONE |

**Live statistics rule:** the homepage's "platform so far" numbers come from the real engine database
(clips rendered, minutes processed). Marketplace numbers show `0` / "opens soon" until real
campaigns exist. Every illustrative card is labelled **Example**; every dashboard preview carries a
**Demo data** banner.

## 4. Clipper dashboard design

Sidebar groups: **Overview** · **Campaigns** (Recommended, Joined, Invitations) · **Clips**
(Submit clip, Submissions, Clip Studio, Library) · **Earnings** (Overview, Payouts) · **Growth**
(Connected accounts, Portfolio, Website analytics, Client enquiries) · **Account** (Notifications, Settings).

Overview screen (built as design preview `/design/clipper`):
- KPI strip: Available balance · Pending rewards · Verified views (30d) · Acceptance rate · Active campaigns.
- Earnings chart (gross vs net after 5% fee).
- Submissions table with the full status vocabulary (Draft → Verification Pending → … → Paid).
- Joined campaigns with funding badge, reward rate, community link state ("Not provided by host" when absent).
- Connected accounts with ownership state (Verified via OAuth / Verified via bio code / Pending manual review / Not verified).
- Submit-clip panel showing the 60-minute countdown rule.

## 5. Campaign manager dashboard design

Sidebar: **Overview** · **Campaigns** (Create, Manage, Funding) · **Review** (Pending, Accepted, Rejected,
Disputes) · **Payouts** (Reward obligations, Payout history) · **Community** (Invitations, Clippers) ·
**Account** (Verification progress, Billing, Settings).

Overview (`/design/manager`): KPIs (funded balance, obligations awaiting payment, pending reviews with
72-hour clocks, verified views, spend), review queue with time-left chips, campaign table with funding
badges, verification progress bar ($1,650 / $2,000 = 82.5%).

Create-campaign screen (`/design/manager/create`): sectioned form for every field in brief §6, funding
method choice with live server-side fee quote, "Save draft" and "Publish" actions.

## 6. Owner Control Centre design

Not linked anywhere public. Production route will sit behind owner-only session + TOTP MFA (Phase 2/13).
Design preview at `/design/owner`, and previews can be switched off with `SCU_DESIGN_PREVIEWS=0`.

Sections: **Finance** (revenue by fee type, gross volume, payouts, refunds, chargebacks, processing
costs, net revenue, owner-available balance, owner payouts) · **Campaigns** (oversight table with
the brief's sort keys, suspend/inspect) · **Clippers** (leaderboard 7/30/90/all) · **Accounts**
(search, verification approvals, suspensions, disputes, activity logs) · **Platform** (fee settings,
categories, analytics charts, exports).

The owner-available balance is defined as platform fee revenue minus refunds/chargebacks/costs
already recognised, and **never** includes reward funds or money owed to clippers (enforced by the
ledger account it reads from, §9).

## 7. Clip Studio interface

Keeps the existing app at `/studio` and adds, in Phase 10:
- Account-scoped projects and library (replace the shared-key gate).
- Post-render editor: transcript-based subtitle editing, trim handles, re-render job.
- Export history per user, token metering (25/clip, 20/download) against plan balance.
- "Use in campaign" action: Create → Export → (user publishes themselves) → Submit URL → Verify → Review.
  The UI never says a clip was published unless a real publishing integration confirmed it.

## 8. Portfolio Builder interface

Editor (`/design/portfolio`): left rail of sections (Hero, About, Verified accounts, Stats, Featured
clips, Previous work, Hire me), centre live preview with desktop/mobile toggle, right panel for the
selected section (text, colours, image upload). Publish / Unpublish / Preview controls. Public
metrics are opt-in per metric and only ever drawn from verified data; earnings are never shown
unless the clipper explicitly enables them.

Public page (`/design/u/demo`, later `/u/{username}`): hero, verified account chips, opted-in stats,
featured clips, Work With Me enquiry form.

---

## 9. Database architecture (PostgreSQL, Phase 2 onward)

Conventions: UUID primary keys, `created_at`/`updated_at` timestamptz, money as **integer minor units
+ ISO currency**, soft deletes only where audit requires it, RLS-equivalent checks enforced in the
service layer on every query (and Postgres RLS policies if Supabase is chosen).

**Identity & roles**
- `users` (email unique, password_hash, mfa_secret_enc, status)
- `user_roles` (user_id, role ∈ clipper|manager|owner, granted_by, granted_at) — `owner` only grantable via a CLI command on the server, never via API.
- `clipper_profiles`, `manager_profiles` (display name, handle unique, verified_at, verification_revoked_at)
- `sessions` (hashed token, user_id, expires_at, ip, ua), `mfa_recovery_codes`

**Social**
- `social_accounts` (user_id, platform, platform_user_id, username, avatar_url, ownership_method ∈ oauth|bio_code|manual, ownership_verified_at, status, token_enc, token_expires_at) — unique (platform, platform_user_id) where verified
- `social_verification_attempts` (social_account_id, method, code_hash, expires_at, result, checked_at, reviewer_id)

**Campaigns**
- `categories` (owner-managed)
- `campaigns` (manager_id, title, brand_name, category_id, description, thumbnail_key, platforms[], rate_per_1k_minor, min_views, max_payout_per_clip_minor, budget_minor, currency, starts_at, ends_at, funding_type ∈ flexible|funded, status ∈ draft|pending_payment|active|paused|completed|suspended, submissions_paused)
- `campaign_requirements` (campaign_id, kind ∈ hashtag|caption|mention|rule|prohibited, value)
- `campaign_assets` (campaign_id, kind ∈ reference_link|example_video|brand_asset|source_video, url_or_key)
- `campaign_invitations` (campaign_id, kind ∈ discord|group_chat|community|private_page, url, active, revoked_at)
- `campaign_participants` (campaign_id, user_id, joined_at, status) — unique (campaign_id, user_id)
- `campaign_announcements`
- `campaign_terms_versions` (campaign_id, version, rate, rules snapshot) — submissions bind to the version in force, so rewards are never altered retroactively.

**Submissions & performance**
- `submissions` (campaign_id, user_id, social_account_id, url, normalized_url unique per campaign, platform_post_id, published_at, received_at (server), terms_version, status)
- `submission_status_events` (submission_id, from, to, actor, reason, at) — every transition
- `submission_verifications` (submission_id, check ∈ url|platform|identity|timestamp|window|duplicate, result ∈ pass|fail|unavailable, evidence jsonb)
- `submission_reviews` (submission_id, reviewer_id, decision, reason, due_at, escalated_at)
- `disputes` (submission_id, opened_by, status, resolution, resolver_id)
- `performance_snapshots` (submission_id, views, likes, comments, shares, source ∈ api|unavailable, fetched_at)
- `fraud_flags` (subject_type, subject_id, rule, details, status ∈ open|cleared|actioned)

**Money (double-entry ledger)**
- `ledger_accounts` (code, owner_type, owner_id, currency, kind) — e.g. `host:{id}:funding`, `campaign:{id}:reserved`, `clipper:{id}:payable`, `platform:fees:host`, `platform:fees:clipper`, `platform:owner_available`, `stripe:clearing`
- `ledger_transactions` (idempotency_key unique, kind, reference_type, reference_id, created_at)
- `ledger_entries` (transaction_id, account_id, amount_minor signed, currency) — DB constraint: each transaction sums to zero per currency
- `reward_calculations` (submission_id, eligible_views, rate, gross_minor, fee_bps, fee_minor, net_minor, terms_version, calculated_at) — unique per submission per measurement window
- `reward_obligations` (submission_id, amount_minor, status ∈ pending|funded|processing|paid|failed|reversed, due_at)
- `payment_intents`, `transfers`, `payouts`, `refunds`, `chargebacks` (provider ids unique)
- `fee_settings` (scope ∈ global|manager|campaign, host_fee_bps, clipper_fee_bps, launch_fee_min/max_minor, valid_from, valid_to, note) — owner-editable, no code change needed
- `webhook_events` (provider, event_id unique, payload, processed_at) — idempotent processing

**Studio, portfolio, retainers, ops**
- `studio_projects`, `processing_jobs`, `job_events`, `transcripts`, `generated_clips` (current tables, gaining `user_id`)
- `token_balances`, `token_events`
- `portfolio_sites` (user_id, slug unique, template, theme jsonb, published_at), `portfolio_sections` (site_id, kind, position, content jsonb), `portfolio_metric_optins`
- `client_enquiries` (clipper_id, name, business, email, description, monthly_needs, budget_range, contact_pref, status), `retainer_agreements`
- `notifications`, `notification_preferences`, `email_outbox`
- `verification_badges` (manager_id, threshold_reached_at, risk_check_result, approved_by, approved_at, revoked_at)
- `admin_actions`, `audit_logs` (actor, action, subject, before/after, ip, at)

Indexes on every foreign key, `(status, created_at)` on queues, `(campaign_id, normalized_url)` unique.

## 10. Payment integration architecture

**Provider:** Stripe Connect, platform-controlled, with Express connected accounts for clippers.
Charges to hosts use **separate charges and transfers**; rewards move by Transfer to the clipper's
connected account; Stripe pays out to their bank.

**Flows**
1. *Flexible (Pay As You Go):* host pays the launch fee (10% of advertised budget, clamped to the
   owner-set min/max) and saves a payment method (SetupIntent). Campaign activates. When rewards
   are approved the host pays the batch (PaymentIntent for gross rewards); on success the ledger
   moves funds to `campaign:reserved`, then Transfers pay clippers. The launch fee is recorded as a
   **host fee credit** that offsets host fees on later reward payments until used up. Badge:
   "Pay As You Go — Rewards Not Pre-Funded". New obligations are blocked above the host's
   authorised limit; a saved card is never shown to clippers as a guarantee.
2. *Fully funded:* host pays budget + 10% fee up front. Fee posts to `platform:fees:host`; budget posts
   to `campaign:reserved`. "Fully Funded" badge appears only after the charge has **settled**
   (`balance_transaction` available), not on payment success.
3. *Clipper fee:* 5% deducted at transfer time; ledger records gross, fee and net; clipper sees all three
   before payout.
4. *Owner payout:* Stripe Payout from platform balance, capped at the `platform:owner_available`
   ledger balance, which can never include reserved or payable funds.

**Reliability:** all maths server-side in integer minor units (`app/fees.py`, DONE and tested);
idempotency keys on every Stripe call and ledger transaction; webhook signature verification;
`webhook_events` de-duplication; nightly reconciliation of ledger vs Stripe balance transactions.

**Must be confirmed before real money (blocking):**
- Stripe's written approval of this marketplace model for a UK platform.
- How long funds may sit in the platform balance before transfer, and per-country availability for
  clippers. Do not assume indefinite holding; unspent funded budgets need a refund rule.
- UK legal advice on whether holding host funds is regulated (payment services / safeguarding) or
  falls within an exemption. The product must not describe itself as escrow.
- Refund, cancellation, review-deadline and payment-deadline terms; tax records (VAT on fees, 1099/
  DAC7-style reporting where Stripe doesn't cover it).

## 11. Implementation sequence

| Phase | Scope | Key dependency |
|---|---|---|
| 1 | Design system, public site, dashboard previews, fee engine | — (**this PR**) |
| 2 | Postgres, accounts, roles, sessions, owner CLI + TOTP | Railway Postgres |
| 3 | Campaign CRUD, drafts, discovery, auto-join, invitations | 2 |
| 4 | Social connections: YouTube OAuth first, then TikTok, Instagram, Facebook; bio-code; manual review | Platform developer apps + review |
| 5 | Submissions: URL parsing, identity + timestamp checks, 60-min window, duplicates, statuses | 4 |
| 6 | Host review queue, 72-h deadlines, reminders, escalation, disputes | 5 |
| 7 | Stripe Connect, ledger, both funding types, fees, payouts, refunds, webhooks | Stripe approval (§10) |
| 8 | View tracking jobs, snapshots, reward calculation | 4, 7 |
| 9 | $2,000 verification threshold, risk checks, owner approval | 7 |
| 10 | Clip Studio: accounts, editor, tokens, Postgres + queue | 2 |
| 11 | Portfolio builder + public `/u/{slug}` | 2, 4 |
| 12 | Client enquiries and inbox | 11 |
| 13 | Owner Control Centre for real | 7–9 |
| 14 | Notifications: in-app + email provider | 2 |
| 15 | Security review, e2e tests, abuse tests | all |
| 16 | Staging + production, monitoring, backups, launch checklist | all |

Recommended deviation: build Phase 7's ledger tables in Phase 3 (no Stripe yet) so campaigns are born
with correct money semantics.

## 12. Technical dependencies and risks

| Dependency | Needed for | Risk |
|---|---|---|
| YouTube Data API (OAuth) | Ownership, `publishedAt`, view counts | Low — well documented; quota limits |
| TikTok Display API | Ownership, post create time, views | Medium — app review; scopes may not cover all accounts |
| Instagram Graph API | Ownership, timestamps, insights | **High** — Business/Creator accounts only; personal accounts fall back to manual review |
| Facebook Graph API | Pages posts | Medium — app review |
| Bio-code checks | Fallback ownership | Must use an authorised read path; scraping profiles is out |
| Stripe Connect | All payments | **High** — approval and fund-holding limits (§10) |
| Email provider (Postmark/Resend/SES) | Notifications | Low |
| OpenAI + Anthropic keys | Clip Studio | Low — already integrated; cost per minute |
| Object storage (S3/R2) | Media at scale | Medium — local disk is fine until multi-instance |
| Legal review | Terms, payouts, fund handling, data protection | **High** — blocks real-money launch |

**Product risks:** the 60-minute rule can only be verified where a platform exposes publish time and
account identity; elsewhere submissions go to *Verification Pending*, which means manual review load.
View counts for Instagram personal accounts may be unavailable, which affects CPM campaigns on that
platform. Fee note: earlier notes recorded a 5% host fee; this brief sets **10%**. Phase 1 uses 10%
as the configurable default.
