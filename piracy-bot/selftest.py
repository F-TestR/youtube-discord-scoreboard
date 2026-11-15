#!/usr/bin/env python3
"""Offline rehearsal: runs the bot four times over a made-up week with FAKE answers
from YouTube, Instagram and Discord, and checks what it would post. Nothing is sent
anywhere and the real data/ folder is not touched.

  python selftest.py            -> prints what each run posted, writes selftest_outbox.json
"""
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sources  # noqa: E402

UTC = dt.timezone.utc
NOW = [None]
SENT = []
FAKE_SHORTS = [  # id, title, posted (UTC), seconds, views per hour for the first day
    ("aaaaaaaaaa1", "Storm battle in PIRACY #roblox #robloxdev", "2026-11-18T18:00:00Z", 24, 95),
    ("aaaaaaaaaa2", "Kraken attack! #roblox", "2026-11-21T17:30:00Z", 19, 20),
]
FAKE_REELS = [("1790001", "Storm battle in PIRACY ⛈️ #roblox", "2026-11-18T19:00:00Z", 30)]
FAKE_SCAN = [(f"bbbbbbbbb{i:02d}", t, c, s, v) for i, (t, c, s, v) in enumerate([
    ("I made a pirate game in 7 days", "DevA", 21, 410000), ("POV: your boat sinks in my Roblox game", "DevB", 14, 220000),
    ("Making waves in Roblox Studio?", "DevC", 33, 90000), ("I made realistic water in Roblox", "DevD", 18, 150000),
    ("This Roblox game has the best ships", "DevE", 45, 60000), ("Roblox devlog #12: sailing", "DevF", 58, 20000),
])]


def views(posted, rate, now):
    hours = max(0.0, (now - sources.parse_time(posted)).total_seconds() / 3600)
    return int(rate * min(hours, 24) + rate * 0.25 * max(0, hours - 24))


def fake_http(method, url, params=None, body=None, headers=None, tries=4):
    now, params = NOW[0], params or {}
    if "discord.com/api/webhooks" in url:
        SENT.append({"method": method, "url": url.split("?")[0][-30:], "body": body})
        return {"id": f"msg{len(SENT)}"} if method == "POST" else {}
    if url.endswith("/channels"):
        return {"items": [{"id": "UCpiracy000000000000000", "contentDetails": {"relatedPlaylists": {"uploads": "UUpiracy"}}}]}
    if url.endswith("/playlistItems"):
        return {"items": [{"contentDetails": {"videoId": v[0]}} for v in FAKE_SHORTS
                          if sources.parse_time(v[2]) <= now]}
    if url.endswith("/search"):
        return {"items": [{"id": {"videoId": v[0]}} for v in FAKE_SCAN]}
    if url.endswith("/videos"):
        out = []
        for vid in params["id"].split(","):
            for v in FAKE_SHORTS:
                if v[0] == vid:
                    vw = views(v[2], v[4], now)
                    out.append({"id": vid, "snippet": {"title": v[1], "channelTitle": "PIRACY", "channelId": "UCpiracy000000000000000",
                                                       "publishedAt": v[2]},
                                "statistics": {"viewCount": str(vw), "likeCount": str(vw // 12), "commentCount": str(vw // 90)},
                                "contentDetails": {"duration": f"PT{v[3]}S"}})
            for i, v in enumerate(FAKE_SCAN):
                if v[0] == vid:
                    out.append({"id": vid, "snippet": {"title": v[1], "channelTitle": v[2], "channelId": f"UC{v[2]}",
                                                       "publishedAt": sources.iso(now - dt.timedelta(days=2 + i))},
                                "statistics": {"viewCount": str(v[4])}, "contentDetails": {"duration": f"PT{v[3]}S"}})
        return {"items": out}
    if "graph.instagram.com" in url and url.endswith("me/media"):
        return {"data": [{"id": r[0], "caption": r[1], "media_product_type": "REELS", "timestamp": r[2],
                          "permalink": f"https://www.instagram.com/reel/{r[0]}/", "like_count": 5, "comments_count": 1}
                         for r in FAKE_REELS if sources.parse_time(r[2]) <= now]}
    if "graph.instagram.com" in url and url.endswith("/insights"):
        r = FAKE_REELS[0]
        vw = views(r[2], r[3], now)
        vals = {"views": vw, "reach": int(vw * .8), "likes": vw // 15, "comments": vw // 100, "shares": vw // 60,
                "saved": vw // 80, "ig_reels_avg_watch_time": 7400, "reels_skip_rate": 41.5, "follows": vw // 120}
        return {"data": [{"name": m, "values": [{"value": vals[m]}]} for m in params["metric"].split(",") if m in vals]}
    if "/invites/" in url:
        return {"approximate_member_count": 37 + 4 * (now.day - 15)}
    raise RuntimeError(f"selftest has no fake answer for {url}")


def main():
    sources.http = fake_http
    tmp = tempfile.mkdtemp(prefix="piracy-selftest-")
    os.environ.update({"BOT_DATA": tmp, "DISCORD_STATS_WEBHOOK": "https://discord.com/api/webhooks/1/selftest",
                       "YOUTUBE_API_KEY": "fake", "INSTAGRAM_TOKEN": "fake", "DRY_RUN": "0"})
    cfg_path = HERE / "config.json"
    cfg = json.loads(cfg_path.read_text())
    import bot
    original_load = bot.load

    def load(path, default):  # use a test handle and an invite code without editing config.json
        if pathlib.Path(path).name == "config.json":
            c = json.loads(json.dumps(cfg))
            c["youtube"]["channel"] = "@piracy"
            c["discord"]["invite_code"] = "piracy"
            return c
        return original_load(path, default)

    bot.load = load
    runs = ["2026-11-16T19:17:00Z", "2026-11-18T21:17:00Z", "2026-11-19T18:17:00Z", "2026-11-23T18:17:00Z"]
    report = []
    for t in runs:
        NOW[0] = sources.parse_time(t)
        os.environ["BOT_NOW"] = t
        before = len(SENT)
        bot.main()
        for s in SENT[before:]:
            emb = (s["body"] or {}).get("embeds", [])
            report.append({"run": t, "method": s["method"],
                           "titles": [e.get("author", {}).get("name", "") + " | " + e.get("title", "") for e in emb]})
            print(f"  {s['method']:5} " + " / ".join(x["title"] or x.get("author", {}).get("name", "") for x in emb))
    (HERE / "selftest_outbox.json").write_text(json.dumps(SENT, ensure_ascii=False, indent=1), encoding="utf-8")
    edits = sum(1 for s in SENT if s["method"] == "PATCH")
    assert edits == len(runs) - 1, "the scoreboard should be edited on every run after the first"
    print(f"\nOK: {len(SENT)} Discord calls over {len(runs)} runs ({edits} scoreboard edits). "
          f"Fake data only; see selftest_outbox.json.")


if __name__ == "__main__":
    main()
