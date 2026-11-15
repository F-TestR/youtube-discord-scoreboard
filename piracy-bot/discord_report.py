"""The look of every PIRACY stats message, and the Monday report.

Messages are built from Discord embed fields: small bold labels over normal-size
values, laid out in columns. Changes use coloured markers that show on desktop
and phones alike: 🟢 up, 🔴 down, 🆕 new.
"""
import datetime as dt

COLOURS = {            # embed side bars, from the PIRACY palette
    "overview": 0x1AA8A0,   # sea teal
    "platforms": 0xC29648,  # worn gold
    "videos": 0x7B4FC0,     # kraken purple
    "notes": 0x5B6572,      # forged iron
    "advice": 0x3BA55C,     # green
    "scan": 0xE8D49A,       # pale gold
}
# name in the tracker, short name
PLATFORMS = [("TikTok", "TikTok"), ("YouTube Shorts", "Shorts"), ("Instagram Reels", "Reels")]
SHORT = dict(PLATFORMS)
MAX_VIDEOS = 5          # newest videos shown in the report
FORMATS_NEEDED = 3      # posts of each format before naming a leader


# ---------------------------------------------------------------- numbers
def n(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def wavg(rows, key):
    pairs = [(n(r.get(key)), n(r.get("views"))) for r in rows]
    pairs = [(v, w) for v, w in pairs if v is not None and w]
    w = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / w if w else None


def stats(rows):
    rows = [r for r in rows if n(r.get("views")) is not None]

    def s(k):
        xs = [n(r.get(k)) for r in rows if n(r.get(k)) is not None]
        return sum(xs) if xs else None

    views, follows, shares = s("views"), s("follows"), s("shares")
    inter = sum(s(k) or 0 for k in ("likes", "comments", "shares", "saves"))
    return {
        "posts": len(rows),
        "videos": len({r.get("video_id") for r in rows}),
        "views": views,
        "likes": s("likes"), "comments": s("comments"), "shares": shares,
        "saves": s("saves"), "follows": follows, "discord_joins": s("discord_joins"),
        "avg_views": views / len(rows) if rows else None,
        "engagement_rate": inter / views if views else None,
        "full_watch_pct": wavg(rows, "full_watch_pct"),
        "follows_per_1k": follows / views * 1000 if views and follows is not None else None,
    }


def fmt_int(v):
    return "—" if v is None else f"{v:,.0f}"


def fmt_pct(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def fmt_short(v):
    """410000 -> 410K"""
    if v is None:
        return "—"
    for div, suffix in ((1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            x = v / div
            return f"{x:.1f}".rstrip("0").rstrip(".") + suffix if x < 10 else f"{x:.0f}{suffix}"
    return f"{v:.0f}"


def fmt_date(iso, year=True):
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return d.strftime("%a %d %b %Y" if year else "%a %d %b").replace(" 0", " ")


def change(cur, prev, kind="int", first=False):
    """🟢 +340 / 🔴 −12 / 🆕 (new) / no change. The sign carries the meaning too."""
    if cur is None:
        return ""
    if first or prev is None:
        return "🆕"
    d = cur - prev
    if kind == "pts":
        d *= 100
    if abs(d) < (0.05 if kind == "pts" else 0.5):
        return "*no change*"
    body = f"{abs(d):,.1f} pts" if kind == "pts" else f"{abs(d):,.0f}"
    return f"🟢 +{body}" if d > 0 else f"🔴 −{body}"


def tile(name, value, chg="", sub=""):
    """One small box: label, big value, then the change under it."""
    lines = [f"**{value}**"] + [x for x in (chg, sub) if x]
    return {"name": name, "value": "\n".join(lines), "inline": True}


def pad_row(fields):
    """Fill the last row of inline fields to three so the columns line up."""
    k = sum(1 for f in fields if f.get("inline")) % 3
    return fields + [{"name": "​", "value": "​", "inline": True}] * ((3 - k) % 3)


# ---------------------------------------------------------------- the Monday report
def build(posts, prev, dashboard_url=None, today=None):
    today = today or dt.date.today().isoformat()
    first = prev is None
    prev = prev or {}
    logged = [r for r in posts if n(r.get("views")) is not None]
    tot = stats(logged)
    ptot, pplat, ppost = prev.get("totals", {}), prev.get("platforms", {}), prev.get("posts", {})
    tiktok_full = wavg([r for r in logged if r.get("platform") == "TikTok"], "full_watch_pct")
    prev_tiktok_full = prev.get("tiktok_full")
    gone = [pid for pid in ppost if pid not in {r.get("post_id") for r in logged}]
    if ppost:
        # compare only posts that are still public, so a video made private or deleted
        # doesn't show up as a drop
        still = [r for r in logged if r.get("post_id") in ppost]
        ptot = stats([ppost[r["post_id"]] for r in still])
        ptot["videos"] = len({r.get("video_id") for r in still})
        pplat = {name: stats([ppost[r["post_id"]] for r in still if r.get("platform") == name])
                 for name, _ in PLATFORMS}
        prev_tiktok_full = wavg([ppost[r["post_id"]] for r in still if r.get("platform") == "TikTok"],
                                "full_watch_pct")
    top = max(logged, key=lambda r: n(r["views"]), default=None)

    # ---- 1. totals
    since = ("*First report: changes start from the next one.*" if first
             else f"*Changes since the last report on {fmt_date(prev.get('date'), False)}.*")
    fields = [
        tile("Views", fmt_int(tot["views"]), change(tot["views"], ptot.get("views"), first=first)),
        tile("Follows", fmt_int(tot["follows"]), change(tot["follows"], ptot.get("follows"), first=first)),
        tile("Engagement", fmt_pct(tot["engagement_rate"]),
             change(tot["engagement_rate"], ptot.get("engagement_rate"), "pts", first)),
        tile("Shares", fmt_int(tot["shares"]), change(tot["shares"], ptot.get("shares"), first=first)),
        tile("Saves", fmt_int(tot["saves"]), change(tot["saves"], ptot.get("saves"), first=first)),
        tile("Comments", fmt_int(tot["comments"]), change(tot["comments"], ptot.get("comments"), first=first)),
        tile("Posts", f"{tot['posts']}", change(tot["posts"], ptot.get("posts"), first=first)),
        tile("Videos", f"{tot['videos']}", change(tot["videos"], ptot.get("videos"), first=first)),
    ]
    if tiktok_full is not None:
        fields.append(tile("TikTok full-watch", fmt_pct(tiktok_full),
                           change(tiktok_full, prev_tiktok_full, "pts", first)))
    overview = {
        "color": COLOURS["overview"],
        "author": {"name": "PIRACY · Weekly report"},
        "title": f"Week to {fmt_date(today)}",
        "description": since,
        "fields": pad_row(fields),
    }
    if dashboard_url:
        overview["url"] = dashboard_url

    # ---- 2. by app
    fields = []
    for name, short in PLATFORMS:
        rows = [r for r in logged if r.get("platform") == name]
        if not rows:
            fields.append({"name": short, "value": "Not logged yet", "inline": True})
            continue
        st, was = stats(rows), pplat.get(name, {})
        lines = [f"**{fmt_int(st['views'])}** views", change(st["views"], was.get("views"), first=first),
                 f"{fmt_pct(st['engagement_rate'])} engagement"]
        if st["full_watch_pct"] is not None:
            lines.append(f"{fmt_pct(st['full_watch_pct'])} {'stayed' if name == 'YouTube Shorts' else 'full-watch'}")
        if st["follows"] is not None:
            lines.append(f"{fmt_int(st['follows'])} follows")
        lines.append(f"{st['posts']} post{'s' if st['posts'] != 1 else ''}")
        fields.append({"name": short, "value": "\n".join(x for x in lines if x), "inline": True})
    platforms = {"color": COLOURS["platforms"], "title": "By app", "fields": fields}
    if any(r.get("source") == "YouTube API" for r in logged):
        platforms["footer"] = {"text": "Shorts engagement counts likes and comments only: YouTube doesn't make shares or saves public."}

    # ---- 3. video by video
    videos = {}
    for r in logged:
        videos.setdefault(r.get("video_id"), []).append(r)
    order = sorted(videos, key=lambda v: min(str(r.get("posted")) for r in videos[v]), reverse=True)
    fields = []
    for vid in order[:MAX_VIDEOS]:
        rows = videos[vid]
        head = rows[0]
        lines = [f"*{head.get('format') or 'No format set'} · posted "
                 f"{fmt_date(min(str(r.get('posted')) for r in rows), False)}*"]
        for name, short in PLATFORMS:
            r = next((x for x in rows if x.get("platform") == name), None)
            if r is None:
                continue
            was = ppost.get(r.get("post_id"))
            st = stats([r])
            chg = change(st["views"], was.get("views") if was else None, first=first or was is None)
            lines.append(f"{short}  **{fmt_int(st['views'])}** views  {chg}  ·  "
                         f"{fmt_pct(st['engagement_rate'])} eng")
        missing = [short for name, short in PLATFORMS if not any(x.get("platform") == name for x in rows)]
        if missing:
            lines.append(f"Not logged on {' or '.join(missing)}")
        fields.append({"name": f"{vid} · {head.get('video') or vid}", "value": "\n".join(lines)[:1024]})
    if len(order) > MAX_VIDEOS:
        fields.append({"name": "​", "value": f"*…and {len(order) - MAX_VIDEOS} older videos on the dashboard.*"})
    videos_embed = {"color": COLOURS["videos"], "title": "Videos, newest first",
                    "fields": fields or [{"name": "​", "value": "No videos logged yet."}]}

    # ---- 4. worth a look
    notes = []
    if top:
        notes.append(f"**Best post:** {top['platform']}, {top.get('video')} ({fmt_int(n(top['views']))} views)")
    if not first:
        gains = [(n(r["views"]) - n(ppost[r["post_id"]].get("views")), r) for r in logged
                 if r.get("post_id") in ppost and n(ppost[r["post_id"]].get("views")) is not None]
        if gains:
            g, r = max(gains, key=lambda x: x[0])
            if g > 0:
                notes.append(f"**Biggest climb:** {r.get('video_id')} on {r['platform']}, +{g:,.0f} views")
    fm = {f: stats([r for r in logged if r.get("format") == f]) for f in ("Gameplay", "Cinematic")}
    g, c = fm["Gameplay"], fm["Cinematic"]
    if g["posts"] >= FORMATS_NEEDED and c["posts"] >= FORMATS_NEEDED and g["avg_views"] and c["avg_views"]:
        lead, lag = ("Gameplay", "cinematic") if g["avg_views"] >= c["avg_views"] else ("Cinematic", "gameplay")
        ratio = max(g["avg_views"], c["avg_views"]) / min(g["avg_views"], c["avg_views"])
        notes.append(f"**Gameplay vs cinematics:** {lead} posts average **{ratio:.1f}×** the views of {lag} ones")
    else:
        notes.append(f"**Gameplay vs cinematics:** too early to call ({g['posts']} gameplay, "
                     f"{c['posts']} cinematic; needs {FORMATS_NEEDED} each)")
    if gone:
        notes.append(f"**No longer counted:** {len(gone)} post{'s' if len(gone) != 1 else ''} made private "
                     "or deleted since the last report")
    early = [r for r in logged if str(r.get("snapshot") or "").startswith("about")]
    if early:
        notes.append("**Early numbers:** " + ", ".join(f"{r.get('video_id')} {r['platform']}" for r in early[:3])
                     + " (taken before 24 h)")
    notes_embed = {"color": COLOURS["notes"], "title": "Worth a look",
                   "description": "\n".join(f"• {x}" for x in notes)}

    state = {
        "date": today, "totals": tot, "tiktok_full": tiktok_full,
        "platforms": {name: stats([r for r in logged if r.get("platform") == name]) for name, _ in PLATFORMS},
        "posts": {r.get("post_id"): stats([r]) for r in logged},
    }
    return [overview, platforms, videos_embed, notes_embed], state
