"""Authoritative fee and reward maths. Server-side only; the browser only ever displays results.

All money is integer minor units (cents/pence). Rates are basis points (1% = 100 bps).
Rounding: platform fees round half-up to the nearest minor unit; rewards round DOWN so a
campaign can never be charged a fraction of a cent more than its rate allows.

Defaults come from the brief (host 10%, clipper 5%) and can be overridden per environment
now, and per campaign/manager from the `fee_settings` table once Phase 2 adds Postgres.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

VERIFICATION_THRESHOLD_MINOR = 200_000  # $2,000 in qualifying completed payouts


@dataclass(frozen=True)
class FeeSettings:
    host_fee_bps: int = 1000
    clipper_fee_bps: int = 500
    launch_fee_min_minor: int = 0
    launch_fee_max_minor: int | None = None  # None = no cap

    @classmethod
    def from_env(cls) -> "FeeSettings":
        cap = os.environ.get("SCU_LAUNCH_FEE_MAX_MINOR", "").strip()
        return cls(
            host_fee_bps=int(os.environ.get("SCU_HOST_FEE_BPS", "1000")),
            clipper_fee_bps=int(os.environ.get("SCU_CLIPPER_FEE_BPS", "500")),
            launch_fee_min_minor=int(os.environ.get("SCU_LAUNCH_FEE_MIN_MINOR", "0")),
            launch_fee_max_minor=int(cap) if cap else None,
        )

    def __post_init__(self):
        for name in ("host_fee_bps", "clipper_fee_bps"):
            v = getattr(self, name)
            if not 0 <= v <= 5000:
                raise ValueError(f"{name} must be between 0 and 5000 bps")
        if self.launch_fee_min_minor < 0:
            raise ValueError("launch_fee_min_minor cannot be negative")
        if self.launch_fee_max_minor is not None and self.launch_fee_max_minor < self.launch_fee_min_minor:
            raise ValueError("launch_fee_max_minor must be >= launch_fee_min_minor")


def _pct(amount_minor: int, bps: int) -> int:
    return int((Decimal(amount_minor) * bps / Decimal(10_000)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _require_amount(amount_minor: int, name: str = "amount") -> None:
    if not isinstance(amount_minor, int) or isinstance(amount_minor, bool):
        raise TypeError(f"{name} must be an integer number of minor units")
    if amount_minor < 0:
        raise ValueError(f"{name} cannot be negative")


def parse_major(value: str | int | float, *, max_major: int = 10_000_000) -> int:
    """'10,000.50' -> 1000050. Rejects negatives, >2 decimals, and absurd sizes."""
    try:
        d = Decimal(str(value).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        raise ValueError("Enter an amount like 10000 or 10000.50")
    if not d.is_finite() or d < 0:
        raise ValueError("Amount must be zero or more")
    if d.as_tuple().exponent < -2:
        raise ValueError("Use at most two decimal places")
    if d > max_major:
        raise ValueError(f"Amount must be at most {max_major:,}")
    return int(d * 100)


# ---------- campaign funding ----------

def quote_funded(budget_minor: int, s: FeeSettings = FeeSettings()) -> dict:
    """Fully funded: host pays reward budget + host fee up front. Fee is recorded separately."""
    _require_amount(budget_minor, "budget")
    fee = _pct(budget_minor, s.host_fee_bps)
    return {"funding_type": "funded", "reward_budget": budget_minor, "host_fee": fee,
            "host_fee_bps": s.host_fee_bps, "due_now": budget_minor + fee,
            "badge_after_settlement": "Fully Funded"}


def launch_fee(advertised_minor: int, s: FeeSettings = FeeSettings()) -> int:
    _require_amount(advertised_minor, "advertised budget")
    fee = max(_pct(advertised_minor, s.host_fee_bps), s.launch_fee_min_minor)
    if s.launch_fee_max_minor is not None:
        fee = min(fee, s.launch_fee_max_minor)
    return fee


def quote_flexible(advertised_minor: int, s: FeeSettings = FeeSettings()) -> dict:
    """Pay As You Go: only the launch fee is due now. The advertised budget is a spending limit,
    not deposited funds. The launch fee becomes a credit against later host fees."""
    fee = launch_fee(advertised_minor, s)
    return {"funding_type": "flexible", "advertised_limit": advertised_minor, "launch_fee": fee,
            "host_fee_bps": s.host_fee_bps, "due_now": fee, "deposited_rewards": 0,
            "host_fee_credit": fee, "badge": "Pay As You Go — Rewards Not Pre-Funded"}


def flexible_batch_charge(rewards_minor: int, credit_available_minor: int, s: FeeSettings = FeeSettings()) -> dict:
    """What a flexible host pays when funding a batch of approved rewards.
    Host fee on the batch is offset by any unused launch-fee credit, so nothing is charged twice."""
    _require_amount(rewards_minor, "rewards")
    _require_amount(credit_available_minor, "credit")
    fee = _pct(rewards_minor, s.host_fee_bps)
    used = min(fee, credit_available_minor)
    return {"rewards": rewards_minor, "host_fee": fee, "credit_used": used, "host_fee_charged": fee - used,
            "credit_remaining": credit_available_minor - used, "due_now": rewards_minor + fee - used}


# ---------- rewards ----------

def gross_reward(eligible_views: int, rate_per_1k_minor: int, *, min_views: int = 0,
                 max_payout_minor: int | None = None) -> int:
    """CPM-style reward. Below the minimum, nothing is earned; above the cap, the cap applies."""
    for v, n in ((eligible_views, "eligible_views"), (rate_per_1k_minor, "rate"), (min_views, "min_views")):
        _require_amount(v, n)
    if eligible_views < min_views:
        return 0
    gross = int((Decimal(eligible_views) * rate_per_1k_minor / Decimal(1000)).quantize(Decimal(1), rounding=ROUND_DOWN))
    if max_payout_minor is not None:
        _require_amount(max_payout_minor, "max_payout")
        gross = min(gross, max_payout_minor)
    return gross


def clipper_payout(gross_minor: int, s: FeeSettings = FeeSettings()) -> dict:
    _require_amount(gross_minor, "gross reward")
    fee = _pct(gross_minor, s.clipper_fee_bps)
    return {"gross": gross_minor, "clipper_fee": fee, "clipper_fee_bps": s.clipper_fee_bps, "net": gross_minor - fee}


def reward_breakdown(eligible_views: int, rate_per_1k_minor: int, *, min_views: int = 0,
                     max_payout_minor: int | None = None, s: FeeSettings = FeeSettings()) -> dict:
    gross = gross_reward(eligible_views, rate_per_1k_minor, min_views=min_views, max_payout_minor=max_payout_minor)
    return {"eligible_views": eligible_views, "rate_per_1k": rate_per_1k_minor,
            "below_minimum": eligible_views < min_views,
            "capped": max_payout_minor is not None and gross == max_payout_minor and eligible_views >= min_views,
            **clipper_payout(gross, s)}


# ---------- manager verification ----------

def verification_progress(qualifying_payouts_minor: int, threshold_minor: int = VERIFICATION_THRESHOLD_MINOR) -> dict:
    _require_amount(qualifying_payouts_minor, "qualifying payouts")
    pct = min(Decimal(100), Decimal(qualifying_payouts_minor) * 100 / threshold_minor).quantize(Decimal("0.1"), rounding=ROUND_DOWN)
    return {"qualifying": qualifying_payouts_minor, "threshold": threshold_minor, "percent": float(pct),
            "eligible_for_review": qualifying_payouts_minor >= threshold_minor}


def settings_dict(s: FeeSettings | None = None) -> dict:
    return asdict(s or FeeSettings.from_env())


def fmt_money(minor: int, currency: str = "$") -> str:
    sign = "-" if minor < 0 else ""
    major, cents = divmod(abs(minor), 100)
    return f"{sign}{currency}{major:,}" + (f".{cents:02d}" if cents else "")
