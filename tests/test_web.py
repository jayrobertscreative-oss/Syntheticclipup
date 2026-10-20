"""Phase 1 web tests: every page renders, honesty rules hold, fee API is server-side and validated.
Run:  python -m unittest discover -s tests -p "test_*.py"
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SCU_DATA_DIR", tempfile.mkdtemp(prefix="scu-web-"))
os.environ.setdefault("SCU_SECRET", "test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient  # noqa: E402

from app import main, web  # noqa: E402

PUBLIC = ["/", "/campaigns", "/clip-studio", "/portfolio-builder", "/how-it-works", "/pricing", "/sign-in", "/get-started", "/legal"]


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = TestClient(main.app)

    def test_public_pages_render(self):
        for p in PUBLIC:
            r = self.c.get(p)
            self.assertEqual(r.status_code, 200, p)
            self.assertIn("SYNTHETIC CLIP UP", r.text, p)
            for label in ("Explore Campaigns", "Clip Studio", "Portfolio Builder", "How It Works", "Pricing", "Sign In", "Get Started"):
                self.assertIn(label, r.text, f"{label} missing from nav on {p}")

    def test_studio_moved_and_still_served(self):
        r = self.c.get("/studio")
        self.assertEqual(r.status_code, 200)
        self.assertIn("/static/app.js", r.text)

    def test_owner_never_offered_at_registration(self):
        r = self.c.get("/get-started?role=owner")
        self.assertNotIn('value="owner"', r.text)
        self.assertIn('value="clipper" checked', r.text)  # unknown role falls back to clipper

    def test_examples_are_labelled(self):
        home = self.c.get("/").text
        self.assertIn("Example", home)
        self.assertIn("Opening soon", home)  # no fake marketplace numbers before launch
        self.assertIn("Pay As You Go — Rewards Not Pre-Funded", self.c.get("/campaigns").text)

    def test_every_dashboard_screen(self):
        for role, groups in web.NAVS.items():
            for _, items in groups:
                for slug, *_ in items:
                    r = self.c.get(f"/design/{role}/{slug}")
                    self.assertEqual(r.status_code, 200, f"{role}/{slug}")
                    self.assertIn("Demo data", r.text, f"{role}/{slug} lacks demo banner")
                    self.assertEqual(r.headers.get("x-robots-tag"), "noindex")
        self.assertEqual(self.c.get("/design/u/demo").status_code, 200)
        self.assertEqual(self.c.get("/design/admin/overview").status_code, 404)

    def test_previews_can_be_disabled(self):
        os.environ["SCU_DESIGN_PREVIEWS"] = "0"
        try:
            self.assertEqual(self.c.get("/design/owner").status_code, 404)
            self.assertEqual(self.c.get("/design").status_code, 404)
        finally:
            os.environ.pop("SCU_DESIGN_PREVIEWS")

    def test_fee_quote_api(self):
        d = self.c.get("/api/fees/quote", params={"mode": "funded", "budget": "10,000"}).json()
        self.assertEqual((d["host_fee"], d["due_now"]), (100_000, 1_100_000))
        d = self.c.get("/api/fees/quote", params={"mode": "flexible", "budget": "10000"}).json()
        self.assertEqual((d["launch_fee"], d["deposited_rewards"]), (100_000, 0))
        d = self.c.get("/api/fees/quote", params={"mode": "reward", "views": "100000", "rate": "2"}).json()
        self.assertEqual((d["gross"], d["clipper_fee"], d["net"]), (20_000, 1_000, 19_000))
        for bad in ({"mode": "funded", "budget": "-1"}, {"mode": "funded", "budget": "x"}, {"mode": "nope"},
                    {"mode": "reward", "views": "-5", "rate": "1"}):
            self.assertEqual(self.c.get("/api/fees/quote", params=bad).status_code, 400, bad)

    def test_fee_quote_public_even_with_access_key(self):
        old = main.config.ACCESS_KEY
        main.config.ACCESS_KEY = "secret"
        try:
            self.assertEqual(self.c.get("/api/fees/quote?mode=funded&budget=1").status_code, 200)
            self.assertEqual(self.c.get("/api/projects").status_code, 401)  # engine API stays gated
        finally:
            main.config.ACCESS_KEY = old

    def test_security_headers(self):
        h = self.c.get("/").headers
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertEqual(h["x-frame-options"], "DENY")


if __name__ == "__main__":
    unittest.main()
