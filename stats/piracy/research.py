"""Research: what's working for other Roblox developers, what the trend bot sees,
and a short field guide drawn from the PIRACY Short-Form Growth handbook.

Everything here is real data or a cited source. Patterns from the scan are described
as patterns ("8 of the 20 fastest are build videos"), never as causes.
"""
import csv
import datetime as dt
import io
import re
import statistics

from . import collect, net, util

PIRATE_WORDS = re.compile(r"\b(pirate|pirates|ship|ships|sea|ocean|kraken|boat|boats|sail|sailing|treasure|island|navy|captain|cannon)\b", re.I)
BUILD_WORDS = re.compile(r"^\s*(making|i made|building|i built|how i made|recreating|i recreated)\b", re.I)


def scan(key, cfg, store_scan, now):
    """Search YouTube for recent Roblox dev Shorts (about 100 quota units per search)."""
    days = cfg.get("days", 7)
    after = util.iso(now - dt.timedelta(days=days))
    found = set()
    for q in cfg.get("queries", []):
        r = net.request("GET", collect.YT + "search", {
            "part": "snippet", "q": q, "type": "video", "videoDuration": "short", "order": "viewCount",
            "publishedAfter": after, "maxResults": 25, "key": key}) or {}
        found |= {it["id"]["videoId"] for it in r.get("items", []) if it.get("id", {}).get("videoId")}
    exclude = set(cfg.get("exclude_channels", []))
    ts = util.iso(now)
    for v in collect.youtube_videos(key, sorted(found)):
        if v["duration_s"] is None or v["duration_s"] > 180 or v["channel_id"] in exclude:
            continue
        cur = store_scan.get(v["id"])
        if cur is None:
            cur = store_scan[v["id"]] = {"first_seen": ts, "first_views": v["views"]}
        cur.update({k: v[k] for k in ("title", "channel", "channel_id", "published", "duration_s", "views",
                                       "likes", "comments", "thumb")})
        cur["last_seen"] = ts
    # forget anything older than 45 days
    cutoff = util.iso(now - dt.timedelta(days=45))
    for vid in [k for k, v in store_scan.items() if (v.get("published") or "") < cutoff]:
        del store_scan[vid]
    return len(found)


def patterns(store_scan, now, days=7, top_n=20):
    rows = []
    for vid, r in store_scan.items():
        if not r.get("published") or not r.get("views"):
            continue
        age_d = max(util.hours_between(r["published"], now) / 24, 0.25)
        if age_d > days + 0.5:
            continue
        rows.append({**r, "id": vid, "per_day": r["views"] / age_d, "age_d": age_d})
    rows.sort(key=lambda r: -r["per_day"])
    top = rows[:top_n]
    out = {"scanned": len(rows), "days": days, "top": [], "stats": [], "pirate": []}
    for r in rows[:12]:
        out["top"].append({"id": r["id"], "title": r["title"], "channel": r["channel"],
                           "duration_s": r["duration_s"], "views": r["views"], "per_day": round(r["per_day"]),
                           "published": r["published"],
                           "thumb": r.get("thumb") or f"https://i.ytimg.com/vi/{r['id']}/hqdefault.jpg",
                           "url": f"https://www.youtube.com/shorts/{r['id']}",
                           "new": util.hours_between(r.get("first_seen", r["published"]), now) < 30})
    if len(top) >= 8:
        n = len(top)
        build = sum(bool(BUILD_WORDS.search(r["title"])) for r in top)
        short30 = sum((r["duration_s"] or 999) <= 30 for r in top)
        med = statistics.median(r["duration_s"] for r in top if r["duration_s"])
        q = sum("?" in r["title"] for r in top)
        caps = sum(bool(re.search(r"\b[A-Z]{4,}\b", r["title"])) for r in top)
        out["stats"] = [
            {"label": "Build videos", "value": f"{build} of {n}", "detail": "titles starting “Making…”, “I made…”, “Building…”"},
            {"label": "Typical length", "value": f"{med:.0f} s", "detail": f"middle length of the {n} fastest"},
            {"label": "30 seconds or shorter", "value": f"{short30} of {n}", "detail": "of the fastest-growing"},
            {"label": "A word in CAPITALS", "value": f"{caps} of {n}", "detail": "e.g. “OP”, “INSANE”"},
            {"label": "A question in the title", "value": f"{q} of {n}", "detail": "titles with a “?”"},
        ]
        out["build_share"] = build / n
        out["n"] = n
    for r in rows:
        if PIRATE_WORDS.search(r["title"] or ""):
            out["pirate"].append({"id": r["id"], "title": r["title"], "channel": r["channel"], "views": r["views"],
                                  "per_day": round(r["per_day"]), "url": f"https://www.youtube.com/shorts/{r['id']}"})
    out["pirate"] = out["pirate"][:6]
    return out


def trendbot(url, site_url):
    """The trend bot's latest board (public), with sea / pirate games flagged."""
    text = net.request("GET", url, raw=True, headers={"Accept": "text/csv"})
    rows = list(csv.DictReader(io.StringIO(text)))
    out = []
    for r in rows[:40]:
        name = r.get("name") or ""
        out.append({"name": name, "players": util.num(r.get("players")), "score": util.num(r.get("trend_score")),
                    "growth": util.num(r.get("growth_vs_last_week")), "reasons": (r.get("reasons") or "")[:160],
                    "age_days": util.num(r.get("age_days")), "id": r.get("universe_id"),
                    "url": f"https://www.roblox.com/games/start?universeId={r.get('universe_id')}" if r.get("universe_id") else None,
                    "sea": bool(PIRATE_WORDS.search(name))})
    return {"rows": out, "site": site_url}


# The field guide: a few well-sourced principles from the PIRACY Short-Form Growth handbook.
# Each says how strong the evidence is. Dates are when the source was published or checked.
FIELD_GUIDE = [
    {"tag": "OFFICIAL", "title": "People choosing to keep watching is what spreads a Short",
     "text": "YouTube says Shorts are shown based on whether viewers watch or swipe away, average view duration, "
             "average percentage viewed and satisfaction. It also says there's no minimum posting schedule.",
     "do": "Judge clips by how many people stay, not just views. Connect YouTube Analytics to see this per Short.",
     "source": "YouTube Help: Search & discovery tips for Shorts", "checked": "Nov 2026",
     "url": "https://support.google.com/youtube/answer/11914225"},
    {"tag": "OFFICIAL", "title": "TikTok weighs watching, finishing and skipping",
     "text": "TikTok's For You feed uses interactions such as watching, watching to the end and skipping, plus "
             "what the video is about. There's no published formula or guaranteed watch-time cut-off.",
     "do": "Make the first frame worth stopping for, and pay it off before the end.",
     "source": "TikTok Support: How TikTok recommends content", "checked": "Nov 2026",
     "url": "https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content"},
    {"tag": "OFFICIAL", "title": "Views aren't the whole story on YouTube",
     "text": "YouTube separates total Shorts views from engaged views and “stayed to watch”, and its view "
             "definitions have changed over time. Check which number you're comparing.",
     "do": "Compare Shorts at the same age and with the same metric, as this site does.",
     "source": "YouTube Help: Shorts analytics", "checked": "Nov 2026",
     "url": "https://support.google.com/youtube/answer/12220281"},
    {"tag": "OFFICIAL", "title": "Track which video brings real players",
     "text": "Roblox share links show which outside source brought people to a game, and how many became "
             "qualified plays and returned.",
     "do": "Before launch, make one share link per app (and per creator) and put it in each bio.",
     "source": "Roblox Creator Docs: Share links", "checked": "Nov 2026",
     "url": "https://create.roblox.com/docs/production/promotion/share-links"},
    {"tag": "CASE STUDY", "title": "Showing the making of the game can build an audience",
     "text": "Mortal Rite's studio reported 120m+ TikTok views and 60k+ Steam wishlists, and credited "
             "progress clips, answering comments and making complex dev work easy to follow. Self-reported, not a trial.",
     "do": "Turn real dev progress into short, clear before/after clips.",
     "source": "Game Developer, 22 Aug 2022", "checked": "Nov 2026",
     "url": "https://www.gamedeveloper.com/game-platforms/this-game-used-tiktok-to-get-120m-views-60k-steam-wishlists-"},
    {"tag": "CASE STUDY", "title": "One clip can change everything, but rarely alone",
     "text": "The Matriarch went from about 400 to 20,000 wishlists after a breakthrough TikTok, alongside a demo "
             "and a Steam event, so TikTok wasn't the only cause.",
     "do": "Keep testing different ideas: breakthroughs come from volume and variety.",
     "source": "Game Developer, 8 Apr 2022", "checked": "Nov 2026",
     "url": "https://www.gamedeveloper.com/game-platforms/from-400-to-20-000-wishlists-with-1-video-how-tiktok-can-make-your-game-go-viral"},
    {"tag": "MYTH", "title": "No magic length, posting time or hashtag count",
     "text": "“15–20 seconds is perfect”, “post at 6pm” and “five hashtags” aren't proven rules. They're ideas to test.",
     "do": "Change one thing at a time and compare at the same age.",
     "source": "PIRACY Short-Form Growth handbook, section 1", "checked": "Nov 2026", "url": None},
]


def experiments(summary, scan, posts_rows):
    """Tests worth running next, each tied to evidence. Status: idea."""
    out = []
    if scan.get("n") and scan.get("build_share", 0) >= 0.25:
        k = round(scan["build_share"] * scan["n"])
        out.append({"title": "Try a build-style Short",
                    "evidence": f"{k} of the {scan['n']} fastest-growing Roblox dev Shorts this week are build videos "
                                "(“Making…”, “I made…”).", "tag": "OBSERVED ELSEWHERE",
                    "test": "Cut a 30–50 second “Building the kraken fight” clip from real dev footage.",
                    "measure": "Views and likes at 24 hours against your usual."})
    yt = [r for r in posts_rows if r["platform"] == "youtube" and r["status"] == "live" and r["curve"].get(24)]
    if len(yt) >= 2:
        yt.sort(key=lambda r: -r["curve"][24])
        out.append({"title": "Name the moment in the title",
                    "evidence": f"Your strongest 24-hour start was “{util.clean_title(yt[0]['title'], 50)}” "
                                f"({util.fmt_int(yt[0]['curve'][24])} views). Compare titles across your next posts.",
                    "tag": "OBSERVED IN ACCOUNT",
                    "test": "For the next two Shorts, put the specific moment in the title (a boss, a ship, a weapon).",
                    "measure": "24-hour views and whether “your usual” moves."})
    out.append({"title": "Design the very first frame",
                "evidence": "Both YouTube and TikTok say watching versus swiping away matters, and the first frame decides that.",
                "tag": "OFFICIAL",
                "test": "Open on the most surprising moment (the kraken, a broadside) instead of a slow build-up.",
                "measure": "Average % viewed once YouTube Analytics is connected; 24-hour views until then."})
    out.append({"title": "Same clip, three apps, same day",
                "evidence": "Posting one clip everywhere within a day lets the site compare apps fairly.",
                "tag": "METHOD",
                "test": "Post each new clip to TikTok, Shorts and Reels within a few hours of each other.",
                "measure": "Each app's 24-hour views for the same clip (shown on the video's page)."})
    return out
