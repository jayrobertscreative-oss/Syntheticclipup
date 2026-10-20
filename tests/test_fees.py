"""Unit tests for app/fees.py. Run:  python -m unittest discover -s tests -p "test_*.py" """
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import fees  # noqa: E402
from app.fees import FeeSettings  # noqa: E402


class BriefExamples(unittest.TestCase):
    """Every worked example in the master brief, reproduced exactly."""

    def test_flexible_10k(self):
        q = fees.quote_flexible(1_000_000)
        self.assertEqual(q["launch_fee"], 100_000)        # $1,000
        self.assertEqual(q["due_now"], 100_000)
        self.assertEqual(q["advertised_limit"], 1_000_000)  # $10,000 is a limit
        self.assertEqual(q["deposited_rewards"], 0)         # ...not deposited funds
        self.assertEqual(q["badge"], "Pay As You Go — Rewards Not Pre-Funded")

    def test_funded_10k(self):
        q = fees.quote_funded(1_000_000)
        self.assertEqual(q["host_fee"], 100_000)
        self.assertEqual(q["due_now"], 1_100_000)           # $11,000 collected
        self.assertEqual(q["reward_budget"], 1_000_000)     # fee recorded separately

    def test_clipper_fee_100(self):
        self.assertEqual(fees.clipper_payout(10_000), {"gross": 10_000, "clipper_fee": 500, "clipper_fee_bps": 500, "net": 9_500})

    def test_cpm_example(self):
        b = fees.reward_breakdown(100_000, 200)             # $2 per 1k, 100k views
        self.assertEqual((b["gross"], b["clipper_fee"], b["net"]), (20_000, 1_000, 19_000))

    def test_verification_progress(self):
        p = fees.verification_progress(165_000)
        self.assertEqual(p["percent"], 82.5)
        self.assertFalse(p["eligible_for_review"])
        self.assertTrue(fees.verification_progress(200_000)["eligible_for_review"])
        self.assertEqual(fees.verification_progress(900_000)["percent"], 100.0)


class Rules(unittest.TestCase):
    def test_reward_minimum_and_cap(self):
        self.assertEqual(fees.gross_reward(999, 100, min_views=1000), 0)
        self.assertEqual(fees.gross_reward(1000, 100, min_views=1000), 100)
        self.assertEqual(fees.gross_reward(10_000_000, 100, max_payout_minor=15_000), 15_000)
        self.assertTrue(fees.reward_breakdown(10_000_000, 100, max_payout_minor=15_000)["capped"])

    def test_reward_rounds_down(self):
        self.assertEqual(fees.gross_reward(1_999, 1), 1)  # 1.999 cents -> 1, never overpays

    def test_fee_rounds_half_up(self):
        self.assertEqual(fees.clipper_payout(10)["clipper_fee"], 1)   # 0.5 -> 1
        self.assertEqual(fees.clipper_payout(9)["clipper_fee"], 0)    # 0.45 -> 0
        for g in (0, 1, 7, 333, 10_001, 123_456_789):
            p = fees.clipper_payout(g)
            self.assertEqual(p["clipper_fee"] + p["net"], g)          # nothing lost or created

    def test_launch_fee_clamps(self):
        s = FeeSettings(launch_fee_min_minor=5_000, launch_fee_max_minor=50_000)
        self.assertEqual(fees.launch_fee(10_000, s), 5_000)       # 10% of $100 = $10 -> min $50
        self.assertEqual(fees.launch_fee(1_000_000, s), 50_000)   # $1,000 -> max $500
        self.assertEqual(fees.launch_fee(200_000, s), 20_000)

    def test_launch_credit_prevents_double_charge(self):
        c = fees.flexible_batch_charge(500_000, credit_available_minor=100_000)  # $5k rewards, $1k credit
        self.assertEqual(c["host_fee"], 50_000)
        self.assertEqual(c["credit_used"], 50_000)
        self.assertEqual(c["host_fee_charged"], 0)
        self.assertEqual(c["credit_remaining"], 50_000)
        self.assertEqual(c["due_now"], 500_000)
        c2 = fees.flexible_batch_charge(800_000, credit_available_minor=c["credit_remaining"])
        self.assertEqual(c2["host_fee_charged"], 30_000)
        self.assertEqual(c2["due_now"], 830_000)
        # Over the whole $13k of rewards, total host fees = 10% exactly.
        self.assertEqual(100_000 + c["host_fee_charged"] + c2["host_fee_charged"], 130_000)

    def test_configurable_rates(self):
        s = FeeSettings(host_fee_bps=750, clipper_fee_bps=300)
        self.assertEqual(fees.quote_funded(1_000_000, s)["host_fee"], 75_000)
        self.assertEqual(fees.clipper_payout(10_000, s)["net"], 9_700)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            fees.quote_funded(-1)
        with self.assertRaises(TypeError):
            fees.quote_funded(10.5)
        with self.assertRaises(TypeError):
            fees.quote_funded(True)
        with self.assertRaises(ValueError):
            FeeSettings(host_fee_bps=-5)
        with self.assertRaises(ValueError):
            FeeSettings(launch_fee_min_minor=100, launch_fee_max_minor=50)

    def test_parse_major(self):
        self.assertEqual(fees.parse_major("10,000"), 1_000_000)
        self.assertEqual(fees.parse_major("$2.50"), 250)
        for bad in ("-1", "abc", "1.005", "nan", "inf", "99999999999"):
            with self.assertRaises(ValueError, msg=bad):
                fees.parse_major(bad)

    def test_fmt_money(self):
        self.assertEqual(fees.fmt_money(110_000_0), "$11,000")
        self.assertEqual(fees.fmt_money(9_550), "$95.50")


if __name__ == "__main__":
    unittest.main()
