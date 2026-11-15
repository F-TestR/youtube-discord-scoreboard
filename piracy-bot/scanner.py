"""Watches other Roblox dev Shorts on YouTube to see what is working right now.

Once a day it searches YouTube for recent Shorts (about 400 of the 10,000 free
daily quota units), keeps their view counts, and works out which are growing
fastest and what they have in common.
"""
import collections
import datetime as dt
import re
import statistics

import sources
from discord_report import COLOURS, fmt_short, tile

STOP = set("""a an and are at be by for from how i in is it its me my of on or our so that the this to
we with you your vs new roblox robloxdev dev devlog game games studio shorts short made making
part day update first look piracy""".split())


def run(key, queries, days, exclude_channels, store, now):
    after = sources.iso(now - dt.timedelta(days=days))
    ids = set()
    for q in queries:
        r = sources.http("GET", sources.YT + "search", {
            "part": "snippet", "type": "video", "q": q, "videoDuration": "short",
            "order": "viewCount", "publishedAfter": after, "maxResults": 25, "key": key})
        ids.update(i["id"]["videoId"] for i in (r or {}).get("items", []) if i.get("id", {}).get("videoId"))
    found = 0
    for v in sources.youtube_videos(key, sorted(ids)):
        if v["duration_s"] is None or v["duration_s"] > 180 or v["channel_id"] in exclude_channels:
            continue
        rec = store.get(v["id"]) or {"first_seen": sources.iso(now), "first_views": v["views"]}
        rec.update({k: v[k] for k in ("title", "channel", "channel_id", "published", "duration_s",
                                       "views", "likes", "comments")})
        rec["last_seen"] = sources.iso(now)
        store[v["id"]] = rec
        found += 1
    cutoff = now - dt.timedelta(days=30)
    for vid in [k for k, r in store.items() if sources.parse_time(r["published"]) < cutoff]:
        del store[vid]
    return found


def summary(store, now, days=14):
    vids = []
    for vid, r in store.items():
        age = max((now - sources.parse_time(r["published"])).total_seconds() / 86400, 0.25)
        if age <= days and r.get("views"):
            vids.append({**r, "id": vid, "per_day": r["views"] / age})
    if not vids:
        return None
    vids.sort(key=lambda r: r["per_day"], reverse=True)
    top = vids[:20]
    words = collections.Counter()
    for r in top:
        for w in set(re.findall(r"[a-z']{3,}", r["title"].lower())):
            if w not in STOP:
                words[w] += 1
    return {
        "count": len(vids),
        "top": vids[:5],
        "median_len_top": statistics.median(r["duration_s"] for r in top),
        "median_len_all": statistics.median(r["duration_s"] for r in vids),
        "short_share": sum(r["duration_s"] <= 30 for r in top) / len(top),
        "question_share": sum("?" in r["title"] for r in top) / len(top),
        "words": [w for w, c in words.most_common(6) if c >= 2],
    }


def embed(s):
    if not s:
        return {"color": COLOURS["scan"], "title": "What's working: Roblox dev Shorts",
                "description": "No scan yet. It runs once a day with the YouTube key."}
    lines = []
    for i, r in enumerate(s["top"], 1):
        title = r["title"].replace("[", "(").replace("]", ")")[:70]
        lines.append(f"**{i}.** [{title}](https://www.youtube.com/shorts/{r['id']})\n"
                     f"{r['channel']} · {r['duration_s']} s · {fmt_short(r['views'])} views · "
                     f"~{fmt_short(r['per_day'])} a day")
    k = min(20, s["count"])
    fields = [
        tile("Typical length", f"{s['median_len_top']:.0f} s", sub=f"fastest {k}"),
        tile("30 s or shorter", f"{s['short_share']:.0%}", sub=f"of the fastest {k}"),
        tile("Question in title", f"{s['question_share']:.0%}", sub=f"of the fastest {k}"),
    ]
    if s["words"]:
        fields.append({"name": "Common title words", "value": ", ".join(s["words"])})
    return {
        "color": COLOURS["scan"],
        "title": "What's working: Roblox dev Shorts",
        "description": "Fastest-growing from the last two weeks, by views per day.\n\n" + "\n\n".join(lines),
        "fields": fields,
        "footer": {"text": "From YouTube search. TikTok can't be scanned automatically, but most devs post the same clips to both."},
    }
