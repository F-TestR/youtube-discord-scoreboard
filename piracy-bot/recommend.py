"""Plain rules that turn the numbers into advice. Each rule waits until there is enough data."""
import statistics

import sources
from discord_report import fmt_int, fmt_pct, n, stats

PLATFORMS = ["TikTok", "YouTube Shorts", "Instagram Reels"]
SLOTS = [("mornings (before 12:00)", 0, 12), ("afternoons (12:00 to 17:00)", 12, 17),
         ("evenings (17:00 to 21:00)", 17, 21), ("late nights (after 21:00)", 21, 24)]


def advice(rows, snaps, scan, now):
    out = []          # (priority, text)
    logged = [r for r in rows if n(r.get("views")) is not None]

    # 1. gameplay or cinematic
    by = {f: [r for r in logged if r.get("format") == f] for f in ("Gameplay", "Cinematic")}
    if all(len(v) >= 3 for v in by.values()):
        g, c = stats(by["Gameplay"]), stats(by["Cinematic"])
        if g["avg_views"] and c["avg_views"]:
            lead, lag, a, b = ("gameplay", "cinematic", g, c) if g["avg_views"] >= c["avg_views"] \
                else ("cinematic", "gameplay", c, g)
            ratio = a["avg_views"] / b["avg_views"]
            if ratio >= 1.3:
                out.append((10, f"**Make more {lead} clips.** They average {ratio:.1f}× the views of "
                                f"{lag} ones ({a['posts']} vs {b['posts']} posts)."))
            else:
                out.append((3, "Gameplay and cinematic clips are performing about the same, so pick "
                               "whichever is quicker to make and post more often."))

    # 2. strongest app, and which turns viewers into followers
    plat = {p: stats([r for r in logged if r["platform"] == p]) for p in PLATFORMS}
    ready = {p: s for p, s in plat.items() if s["posts"] >= 2 and s["avg_views"]}
    if len(ready) >= 2:
        best = max(ready, key=lambda p: ready[p]["avg_views"])
        worst = min(ready, key=lambda p: ready[p]["avg_views"])
        if ready[best]["avg_views"] >= 1.5 * ready[worst]["avg_views"]:
            out.append((7, f"**{best} is your strongest app** at {fmt_int(ready[best]['avg_views'])} views "
                           f"a post, against {fmt_int(ready[worst]['avg_views'])} on {worst}. Post there first."))
        conv = {p: s["follows_per_1k"] for p, s in ready.items() if s["follows_per_1k"] is not None}
        if len(conv) >= 2:
            p = max(conv, key=conv.get)
            out.append((5, f"**{p} turns viewers into followers best**: {conv[p]:.1f} follows per "
                           "1,000 views. End clips there with the strongest follow and Discord prompt."))

    # 3. hooks and retention
    tt = [r for r in logged if r["platform"] == "TikTok" and r.get("full_watch_pct") is not None]
    if len(tt) >= 2:
        fw = stats(tt)["full_watch_pct"]
        if fw is not None and fw < 0.20:
            out.append((9, f"**Hook earlier on TikTok.** Only {fmt_pct(fw)} watch to the end. Open on the "
                           "action itself (the cannon shot, the wave hitting) in the first second, "
                           "and cut anything before it."))
    ig = [r for r in logged if r["platform"] == "Instagram Reels" and r.get("skip_rate") is not None]
    if len(ig) >= 2:
        skip = statistics.mean(r["skip_rate"] for r in ig)
        if skip > 0.5:
            out.append((8, f"**{skip:.0%} of Reels viewers swipe away in the first seconds.** "
                           "Put the most exciting frame first and add on-screen text that says what's coming."))

    # 4. the most shareable clip
    shareable = [r for r in logged if (n(r["views"]) or 0) >= 300 and r.get("shares") is not None]
    if len(shareable) >= 3:
        r = max(shareable, key=lambda r: r["shares"] / r["views"])
        per = r["shares"] / r["views"] * 1000
        out.append((6, f"**{r['video_id']} · {r['video']}** gets shared most ({per:.1f} per 1,000 views "
                       f"on {r['platform']}). Shares mean people send it to friends, so make a follow-up "
                       "in the same style."))

    # 5. best time of day (24-hour views, UK time)
    slot_views = {}
    for r in logged:
        s = snaps.get(r["post_id"], {}).get("24")
        if not s or s.get("views") is None:
            continue
        hour = sources.parse_time(r["posted_at"]).astimezone(sources.UK).hour
        for name, lo, hi in SLOTS:
            if lo <= hour < hi:
                slot_views.setdefault(name, []).append(s["views"])
    slot_views = {k: v for k, v in slot_views.items() if len(v) >= 3}
    if len(slot_views) >= 2:
        med = {k: statistics.median(v) for k, v in slot_views.items()}
        best = max(med, key=med.get)
        rest = statistics.median([x for k, v in slot_views.items() if k != best for x in v])
        if rest and med[best] >= 1.3 * rest:
            out.append((6, f"**Post in the {best}.** Those posts get {med[best] / rest:.1f}× the "
                           "24-hour views of the rest."))

    # 6. keeping the account active
    if logged:
        last = max(sources.parse_time(r["posted_at"]) for r in logged)
        gap = (now - last).days
        if gap >= 4:
            out.append((8, f"**It's been {gap} days since the last post.** Even a short gameplay clip "
                           "keeps the account in people's feeds."))

    # 7. length, against what is growing fastest in Roblox dev Shorts
    lens = [r["duration_s"] for r in logged if r.get("duration_s")]
    if scan and len(lens) >= 3:
        mine, theirs = statistics.median(lens), scan["median_len_top"]
        if mine > 1.4 * theirs:
            out.append((6, f"**Try tighter cuts.** The fastest-growing Roblox dev Shorts run about "
                           f"{theirs:.0f} s; yours average {mine:.0f} s."))

    # 8. a clip that is only on one app
    for vid in sorted({r["video_id"] for r in logged}):
        ps = [r for r in logged if r["video_id"] == vid]
        age = (now - min(sources.parse_time(r["posted_at"]) for r in ps)).days
        if len({r["platform"] for r in ps}) == 1 and 3 <= age <= 21:
            out.append((4, f"**{vid} · {ps[0]['video']}** is only on {ps[0]['platform']}. "
                           "Cross-post it: Shorts and Reels give a clip a second run."))
            break

    out.sort(key=lambda x: -x[0])
    return [t for _, t in out]
