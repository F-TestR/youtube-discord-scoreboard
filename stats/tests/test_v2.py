"""Offline checks for the V2 bot. Nothing touches the internet: tests/fakes.py pretends to be
YouTube, TikTok, Google, Discord and the trend bot.

The rehearsal runs the real bot through eight days of hourly-ish runs with new uploads,
a video made private, a YouTube outage, TikTok getting connected and the weekly report.
"""
import datetime as dt
import importlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from fakes import FakePost, FakeWorld  # noqa: E402
from piracy import analysis, discord_v2 as D, net, util, vault as V  # noqa: E402


class NetTests(unittest.TestCase):
    def test_scrub_hides_secrets(self):
        s = net.scrub("https://x/v3/videos?key=AIzaSECRET&id=1 https://discord.com/api/webhooks/123/tok-en_SECRET "
                      "refresh_token=abc client_secret=xyz")
        for bad in ("AIzaSECRET", "tok-en_SECRET", "abc", "xyz"):
            self.assertNotIn(bad, s)

    def test_retries_rate_limits(self):
        calls = []

        def t(method, url, data, headers, timeout):
            calls.append(1)
            return (429, b'{"retry_after": 0.01}', {}) if len(calls) < 3 else (200, b'{"ok": true}', {})
        old, olds = net.transport, net.sleep
        net.transport, net.sleep = t, lambda s: None
        try:
            self.assertEqual(net.request("GET", "https://example.com"), {"ok": True})
            self.assertEqual(len(calls), 3)
        finally:
            net.transport, net.sleep = old, olds

    def test_error_message_has_no_key(self):
        def t(method, url, data, headers, timeout):
            return 403, b'{"error": "bad key=AIzaSECRET"}', {}
        old = net.transport
        net.transport = t
        try:
            with self.assertRaises(net.HTTPError) as cm:
                net.request("GET", "https://www.googleapis.com/youtube/v3/videos", {"key": "AIzaSECRET"})
            self.assertNotIn("AIzaSECRET", str(cm.exception))
        finally:
            net.transport = old


class VaultTests(unittest.TestCase):
    def test_round_trip_and_wrong_secret(self):
        with tempfile.TemporaryDirectory() as d:
            v = V.Vault(pathlib.Path(d) / "vault.json")
            v.put("tiktok", "secret-1", {"refresh_token": "rt"}, {"connected": "now"})
            v.save()
            raw = (pathlib.Path(d) / "vault.json").read_text()
            self.assertNotIn("rt\"", raw)
            v2 = V.Vault(pathlib.Path(d) / "vault.json")
            self.assertEqual(v2.get("tiktok", "secret-1"), {"refresh_token": "rt"})
            self.assertIsNone(v2.get("tiktok", "secret-2"))
            self.assertEqual(v2.meta("tiktok"), {"connected": "now"})


class DiscordTests(unittest.TestCase):
    def test_validate_limits(self):
        big = [D.card([D.text("x" * 3999), D.text("y" * 5)], 1)]
        with self.assertRaises(ValueError):
            D.validate(big)
        with self.assertRaises(ValueError):
            D.validate([D.row([D.link("a", "http://insecure")])])
        self.assertTrue(D.validate([D.card([D.text("hi")], 1), D.row([D.link("Go", "https://x.y")])]))


class AnalysisTests(unittest.TestCase):
    def test_value_at_needs_close_readings(self):
        t0 = util.parse("2026-11-16T00:00:00Z")
        pts = [(t0, 0.0), (t0 + dt.timedelta(hours=14), 1000.0), (t0 + dt.timedelta(hours=16), 1100.0)]
        self.assertIsNone(analysis.value_at(pts, t0 + dt.timedelta(hours=1)))       # only the posting moment before
        self.assertAlmostEqual(analysis.value_at(pts, t0 + dt.timedelta(hours=15)), 1050.0)

    def test_crossings_collapse_before_tracking(self):
        series = [("a", 1200), ("b", 2600), ("c", 2700)]
        got = analysis.crossings(series, analysis.VIEW_STEPS)
        self.assertEqual(got[0], (1000, "a", True))
        self.assertEqual(got[1], (2500, "b", False))
        self.assertEqual(len(got), 2)


BOARD = "universe_id,name,players,trend_score,reasons,growth_vs_last_week\n1,Pirate Bay Tycoon,500,40,players ×3,3.0\n2,Dig a Hole,9000,55,big rise,2.0\n"


class Rehearsal(unittest.TestCase):
    """Eight days of runs through the real bot with a pretend internet."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        data = cls.tmp / "data"
        shutil.copytree(HERE.parent / "data", data)
        (data / "vault.json").unlink(missing_ok=True)
        (data / "outbox.json").unlink(missing_ok=True)
        os.environ.update({"STATS_DATA": str(data), "STATS_SITE": str(cls.tmp / "site"),
                           "YOUTUBE_API_KEY": "yt-key", "DISCORD_STATS_WEBHOOK": "https://discord.com/api/webhooks/1/hook",
                           "DISCORD_TABS_WEBHOOK": "https://discord.com/api/webhooks/2/tabs",
                           "TIKTOK_CLIENT_KEY": "tt-key", "TIKTOK_CLIENT_SECRET": "tt-secret",
                           "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "", "INSTAGRAM_TOKEN": "", "DRY_RUN": ""})
        start = util.parse("2026-11-18T02:07:00Z")
        cls.world = world = FakeWorld(start, youtube=[
            FakePost("Thxs9ZZ0VD8", "Cannon to the Kraken (cutscene)", "2026-11-15T02:48:26Z", 1350, 6.4, 0.009, 24),
            FakePost("hcNvPpxCBxI", "wait this is actually ROBLOX?? (new pirate game)", "2026-11-16T22:21:03Z", 400, 180, 0.055, 19),
            FakePost("Wp2pwWQsNOk", "New Roblox Pirate Game Has a Submarine Boss", "2026-11-16T23:14:31Z", 1310, 3.4, 0.018, 28),
            FakePost("newShort001", "Broadside at sunset", "2026-11-19T18:00:00Z", 4200, 8, 0.03, 31),
            FakePost("newShort002", "Kraken fight but the ship sinks", "2026-11-21T18:30:00Z", 900, 10, 0.02, 22,
                     private_at="2026-11-24T12:00:00Z"),
            FakePost("newShort003", "Building the kraken in 30 seconds", "2026-11-23T17:00:00Z", 16000, 6, 0.04, 33),
        ], tiktok=[
            FakePost("7300000000000000001", "Cannon to the Kraken", "2026-11-15T12:00:00Z", 2000, 20, 0.08, 24),
            FakePost("7300000000000000002", "Broadside at sunset", "2026-11-19T18:10:00Z", 9000, 12, 0.08, 31),
        ], subs=41, members=12, board_csv=BOARD)
        net.transport = world.transport
        net.sleep = lambda s: None
        D.time.sleep = lambda s: None
        # turn Discord on, as after the switch-over
        cfg = json.loads((HERE.parent / "config.json").read_text())
        cfg["discord"]["live"] = True
        cfg["site"]["ready"] = True
        (cls.tmp / "config.json").write_text(json.dumps(cfg))
        os.environ["STATS_CONFIG"] = str(cls.tmp / "config.json")
        import run
        cls.bot = importlib.reload(run)
        cls.runs = []
        t = start
        end = util.parse("2026-11-25T23:00:00Z")
        connected = False
        while t <= end:
            world.now = t
            os.environ["BOT_NOW"] = util.iso(t)
            # YouTube is down for a while on 22 Nov
            world.fail = {"youtube"} if util.parse("2026-11-22T00:00:00Z") <= t < util.parse("2026-11-22T12:00:00Z") else set()
            # TikTok gets connected on 20 Nov
            if not connected and t >= util.parse("2026-11-20T10:00:00Z"):
                from piracy import collect
                vault = V.Vault(data / "vault.json")
                collect.store_tiktok(vault, "tt-secret", {"access_token": "at-1", "refresh_token": "rt-1",
                                                          "expires_in": 86400, "refresh_expires_in": 31536000}, t)
                vault.save()
                connected = True
            before = len(world.sent)
            cls.bot.main()
            cls.runs.append((t, world.sent[before:]))
            t += dt.timedelta(hours=2)
        cls.data = data

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("STATS_CONFIG", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def kinds(self):
        out = []
        for t, calls in self.runs:
            for c in calls:
                body = c["body"] or {}
                text = json.dumps(body.get("components", []), ensure_ascii=False)
                out.append((t, c["method"], c["path"], text, c))
        return out

    def test_takes_over_the_v1_scoreboard(self):
        first = self.runs[0][1]
        board = [c for c in first if "/webhooks/1/" in c["path"] and "Live stats" in json.dumps(c["body"])]
        self.assertEqual(board[0]["method"], "PATCH")
        self.assertTrue(board[0]["path"].endswith("/1571592035369222409"))
        self.assertEqual(board[0]["body"]["flags"], D.V2)

    def test_scoreboard_edited_not_reposted(self):
        posts = [k for k in self.kinds() if k[1] == "POST" and "Live stats" in k[3]]
        self.assertEqual(posts, [], "the scoreboard should only ever be edited")
        edits = [k for k in self.kinds() if k[1] == "PATCH" and "Live stats" in k[3]]
        self.assertEqual(len(edits), len(self.runs))
        self.assertTrue(all(k[4]["body"].get("_files") == 1 for k in edits), "every edit carries the chart")

    def test_each_alert_once(self):
        seen = {}
        for t, method, path, text, c in self.kinds():
            if method != "POST" or "/webhooks/1/" not in path:
                continue
            key = text
            self.assertNotIn(key, seen, f"duplicate message at {t}: {key}")
            seen[key] = t
        new = [k for k in self.kinds() if k[1] == "POST" and "New on" in k[3]]
        titles = " ".join(k[3] for k in new)
        for t in ("Broadside at sunset", "Kraken fight", "Building the kraken"):
            self.assertIn(t, titles)
        self.assertNotIn("Cannon to the Kraken", titles, "old videos must not be announced again")

    def test_milestones_and_takeoff(self):
        texts = " ".join(k[3] for k in self.kinds() if k[1] == "POST")
        self.assertIn("Milestone", texts)
        self.assertIn("passed 10,000 total views", texts)
        self.assertIn("Taking off", texts)

    def test_health_alert_once_and_recovery(self):
        texts = [k[3] for k in self.kinds() if k[1] == "POST"]
        self.assertEqual(sum("needs a look" in t for t in texts), 1)
        self.assertEqual(sum("is back" in t for t in texts), 1)

    def test_numbers_kept_during_outage(self):
        posts = json.loads((self.data / "posts.json").read_text())
        self.assertGreater(posts["yt:Thxs9ZZ0VD8"]["metrics"]["views"], 1000)
        runs = json.loads((self.data / "runs.json").read_text())
        stale = [r for r in runs if r["statuses"].get("youtube") == "stale"]
        self.assertGreaterEqual(len(stale), 5)

    def test_private_video_stops_counting(self):
        posts = json.loads((self.data / "posts.json").read_text())
        self.assertEqual(posts["yt:newShort002"]["status"], "gone")

    def test_tiktok_connected_and_typed_row_retired(self):
        posts = json.loads((self.data / "posts.json").read_text())
        self.assertEqual(posts["tt:2026-11-15-cannon-to-the-kraken-cutscene"]["status"], "superseded")
        self.assertEqual(posts["tt:7300000000000000002"]["status"], "live")
        vault = V.Vault(self.data / "vault.json")
        tok = vault.get("tiktok", "tt-secret")
        self.assertEqual(tok["refresh_token"], self.world.tt_refresh, "the newest refresh token must be saved")

    def test_weekly_report_once(self):
        weekly = [k for k in self.kinds() if k[1] == "POST" and "Weekly report" in k[3]]
        self.assertEqual(len(weekly), 1)
        self.assertGreaterEqual(weekly[0][0], util.parse("2026-11-23T18:00:00Z"))

    def test_tabs_edited(self):
        tab_posts = [k for k in self.kinds() if "/webhooks/2/" in k[2] and k[1] == "POST"]
        self.assertLessEqual(len(tab_posts), 3)

    def test_site_data(self):
        d = json.loads((self.tmp / "site" / "data.json").read_text())
        self.assertIn("youtube", d["series"])
        self.assertTrue(any(p["platform"] == "tiktok" and p["source"] == "api" for p in d["posts"]))
        self.assertLess(len(json.dumps(d)), 2_000_000)
        yt = d["summary"]["platforms"]["youtube"]
        self.assertIsNotNone(yt["gain_24h"])
        self.assertEqual(yt["followers"], 41)
        self.assertTrue((self.tmp / "site" / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
