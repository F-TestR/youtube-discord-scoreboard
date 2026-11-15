#!/usr/bin/env python3
"""PIRACY stats -> Discord.

Posts a report of the PIRACY social numbers to a Discord channel through a
webhook. It reads the same posts.json that the analytics dashboard uses.
Changes (up/down arrows, green/red) are measured against the last report,
which is kept in a small state file.

  python discord_report.py posts.json --state last_report.json             post it
  python discord_report.py posts.json --state last_report.json --dry-run   only write payload.json

The webhook URL comes from the DISCORD_STATS_WEBHOOK environment variable.
Optional: DASHBOARD_URL makes the report's title a link to the dashboard.
Standard library only, Python 3.8+.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------- settings
BOT_NAME = "PIRACY Stats"
COLOURS = {            # embed side bars, from the PIRACY palette
    "overview": 0x1AA8A0,   # sea teal
    "platforms": 0xC29648,  # worn gold
    "videos": 0x7B4FC0,     # kraken purple
    "notes": 0x5B6572,      # forged iron
}
# name in the tracker, short name, ANSI colour
PLATFORMS = [
    ("TikTok", "TikTok", 36),
    ("YouTube Shorts", "Shorts", 31),
    ("Instagram Reels", "Reels", 35),
]
MAX_VIDEOS = 5          # newest videos shown in the "Video by video" embed
FORMATS_NEEDED = 3      # posts of each format before naming a leader

# ---------------------------------------------------------------- ANSI text
ESC = "\u001b"
GRAY, RED, GREEN, YELLOW, BLUE, PINK, CYAN, WHITE = 30, 31, 32, 33, 34, 35, 36, 37
ANSI_WHITE = WHITE


def ansi(text, colour=None, bold=False):
    if colour is None and not bold:
        return text
    codes = ("1" if bold else "0") + (f";{colour}" if colour else "")
    return f"{ESC}[{codes}m{text}{ESC}[0m"


def block(lines):
    return "```ansi\n" + "\n".join(lines) + "\n```"


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


def fmt_date(iso, year=True):
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return d.strftime("%a %d %b %Y" if year else "%a %d %b").replace(" 0", " ")


def change(cur, prev, kind="int", first=False):
    """Coloured change since the last report. The arrow and sign carry the
    meaning too, because Discord on phones shows code blocks without colour."""
    if cur is None:
        return ansi("—", GRAY)
    if first or prev is None:
        return ansi("NEW", BLUE, bold=True)
    d = cur - prev
    if kind == "pts":
        d *= 100
    if abs(d) < (0.05 if kind == "pts" else 0.5):
        return ansi("±0", GRAY)
    arrow, colour = ("▲", GREEN) if d > 0 else ("▼", RED)
    text = f"{arrow} {d:+,.1f} pts" if kind == "pts" else f"{arrow} {d:+,.0f}"
    return ansi(text, colour, bold=True)


# ---------------------------------------------------------------- report
def build(posts, prev, dashboard_url=None, today=None):
    today = today or dt.date.today().isoformat()
    first = prev is None
    prev = prev or {}
    logged = [r for r in posts if n(r.get("views")) is not None]
    tot = stats(logged)
    ptot = prev.get("totals", {})
    pplat = prev.get("platforms", {})
    ppost = prev.get("posts", {})
    tiktok_full = wavg([r for r in logged if r.get("platform") == "TikTok"], "full_watch_pct")
    top = max(logged, key=lambda r: n(r["views"]), default=None)

    # ---- 1. overview
    since = ("First report: changes (▲ ▼) start from the next one."
             if first else f"Changes are since the last report on {fmt_date(prev.get('date'))}.")
    lines = []
    for label, key, kind, f in [
        ("Views", "views", "int", fmt_int),
        ("Follows", "follows", "int", fmt_int),
        ("Engagement", "engagement_rate", "pts", fmt_pct),
        ("Shares", "shares", "int", fmt_int),
        ("Saves", "saves", "int", fmt_int),
        ("Comments", "comments", "int", fmt_int),
    ]:
        lines.append(f"{label:<12}{ansi(f(tot[key]).rjust(7), WHITE, bold=True)}  "
                     f"{change(tot[key], ptot.get(key), kind, first)}")
    lines.append(f"{'TikTok full':<12}{ansi(fmt_pct(tiktok_full).rjust(7), WHITE, bold=True)}  "
                 f"{change(tiktok_full, prev.get('tiktok_full'), 'pts', first)}")
    joins = tot["discord_joins"]
    lines.append(f"{'Discord':<12}{ansi(fmt_int(joins).rjust(7), WHITE, bold=True)}  "
                 + (change(joins, ptot.get('discord_joins'), 'int', first) if joins is not None
                    else ansi("not logged", GRAY)))
    summary = (f"**{fmt_int(tot['views'])}** views from **{tot['posts']}** "
               f"post{'s' if tot['posts'] != 1 else ''} of **{tot['videos']}** "
               f"video{'s' if tot['videos'] != 1 else ''}, "
               f"**{fmt_int(tot['follows'])}** new follows.")
    overview = {
        "color": COLOURS["overview"],
        "author": {"name": "PIRACY · Social report"},
        "title": f"Report for {fmt_date(today)}",
        "description": f"{summary}\n{since}\n{block(lines)}",
    }
    if dashboard_url:
        overview["url"] = dashboard_url

    # ---- 2. platforms
    lines = []
    for name, short, colour in PLATFORMS:
        rows = [r for r in logged if r.get("platform") == name]
        st = stats(rows)
        if not rows:
            lines.append(f"{ansi(short.ljust(8), colour, bold=True)}{ansi('not logged yet', GRAY)}")
            continue
        was = pplat.get(name, {})
        lines.append(f"{ansi(short.ljust(8), colour, bold=True)}"
                     f"{ansi(fmt_int(st['views']).rjust(7), WHITE, bold=True)} views  "
                     f"{change(st['views'], was.get('views'), 'int', first)}")
        full = "full-watch" if name != "YouTube Shorts" else "stayed"
        eng = f"  {fmt_pct(st['engagement_rate'])} engagement"
        if not first and was:
            eng += "  " + change(st["engagement_rate"], was.get("engagement_rate"), "pts")
        lines.append(eng)
        bits = []
        if st["full_watch_pct"] is not None:
            bits.append(f"{fmt_pct(st['full_watch_pct'])} {full}")
        if st["follows"] is not None:
            bits.append(f"{fmt_int(st['follows'])} follows")
        if bits:
            lines.append("  " + " · ".join(bits))
        lines.append(ansi(f"  {st['posts']} post{'s' if st['posts'] != 1 else ''}", GRAY))
    platforms = {
        "color": COLOURS["platforms"],
        "title": "Platforms",
        "description": "Every logged post on each app. *Shorts \"stayed\" is YouTube's "
                       "stayed-to-watch, not full-watch, so compare it only with other Shorts.*\n"
                       + block(lines),
    }

    # ---- 3. video by video
    videos = {}
    for r in logged:
        videos.setdefault(r.get("video_id"), []).append(r)
    order = sorted(videos, key=lambda v: min(str(r.get("posted")) for r in videos[v]), reverse=True)
    parts = []
    for vid in order[:MAX_VIDEOS]:
        rows = videos[vid]
        head = rows[0]
        lines = [ansi(f"{'':8}{'VIEWS':>7}  CHANGE   ENG", GRAY)]
        for name, short, colour in PLATFORMS:
            r = next((x for x in rows if x.get("platform") == name), None)
            if r is None:
                lines.append(f"{ansi(short.ljust(8), colour, bold=True)}{ansi('not logged', GRAY)}")
                continue
            was = ppost.get(r.get("post_id"))
            st = stats([r])
            ch = change(st["views"], was.get("views") if was else None, "int", first or was is None)
            pad = " " * max(1, 9 - len(ch.split("m", 1)[-1].rsplit(ESC, 1)[0]))
            lines.append(f"{ansi(short.ljust(8), colour, bold=True)}"
                         f"{ansi(fmt_int(st['views']).rjust(7), WHITE, bold=True)}  "
                         f"{ch}{pad}{fmt_pct(st['engagement_rate'])}")
        first_posted = min(str(r.get("posted")) for r in rows)
        parts.append(f"**{vid} · {head.get('video') or vid}**\n"
                     f"{head.get('format') or 'No format set'} · first posted {fmt_date(first_posted, False)}\n"
                     + block(lines))
    if len(order) > MAX_VIDEOS:
        parts.append(f"*…and {len(order) - MAX_VIDEOS} older videos on the dashboard.*")
    videos_embed = {
        "color": COLOURS["videos"],
        "title": "Video by video",
        "description": ("Newest first.\n\n" + "\n".join(parts)) if parts else "No videos logged yet.",
    }

    # ---- 4. notes
    notes = []
    if top:
        notes.append(f"**Best post:** {top['platform']} · {top.get('video')} "
                     f"with {fmt_int(n(top['views']))} views")
    if not first:
        gains = []
        for r in logged:
            was = ppost.get(r.get("post_id"))
            if was and n(was.get("views")) is not None:
                gains.append((n(r["views"]) - n(was["views"]), r))
        if gains:
            g, r = max(gains, key=lambda x: x[0])
            if g > 0:
                notes.append(f"**Biggest climb:** {r.get('video_id')} on {r['platform']}, "
                             f"+{g:,.0f} views since last report")
    fm = {f: stats([r for r in logged if r.get("format") == f]) for f in ("Gameplay", "Cinematic")}
    g, c = fm["Gameplay"], fm["Cinematic"]
    if g["posts"] >= FORMATS_NEEDED and c["posts"] >= FORMATS_NEEDED and g["avg_views"] and c["avg_views"]:
        lead, lag = ("Gameplay", "cinematic") if g["avg_views"] >= c["avg_views"] else ("Cinematic", "gameplay")
        ratio = max(g["avg_views"], c["avg_views"]) / min(g["avg_views"], c["avg_views"])
        notes.append(f"**Gameplay vs cinematics:** {lead} posts are averaging "
                     f"**{ratio:.1f}×** the views of {lag} posts.")
    else:
        notes.append(f"**Gameplay vs cinematics:** too early to call. {g['posts']} gameplay and "
                     f"{c['posts']} cinematic posts logged; each needs {FORMATS_NEEDED}.")
    todo = []
    for vid in order[:MAX_VIDEOS]:
        have = {r.get("platform") for r in videos[vid]}
        missing = [short for name, short, _ in PLATFORMS if name not in have]
        if missing:
            todo.append(f"{vid} on {' and '.join(missing)}")
    if todo:
        notes.append("**Still to log:** " + "; ".join(todo[:4]))
    early = [r for r in logged if str(r.get("snapshot") or "").startswith("about")]
    if early:
        notes.append("**Early numbers:** " + "; ".join(
            f"{r.get('video_id')} {r['platform']} ({r.get('snapshot')})" for r in early[:3])
            + ". Update with the 24 h and 7-day figures.")
    notes_embed = {
        "color": COLOURS["notes"],
        "title": "Worth a look",
        "description": "\n".join(f"• {x}" for x in notes),
        "footer": {"text": "From the PIRACY tracker · ▲ up ▼ down since the last report · "
                           "colours show on desktop"},
        "timestamp": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    }

    state = {
        "date": today,
        "totals": tot,
        "tiktok_full": tiktok_full,
        "platforms": {name: stats([r for r in logged if r.get("platform") == name]) for name, _, _ in PLATFORMS},
        "posts": {r.get("post_id"): stats([r]) for r in logged},
    }
    return [overview, platforms, videos_embed, notes_embed], state


# ---------------------------------------------------------------- sending
def embed_size(e):
    size = len(e.get("title", "")) + len(e.get("description", ""))
    size += len(e.get("author", {}).get("name", "")) + len(e.get("footer", {}).get("text", ""))
    return size


def pack(embeds):
    """Discord allows 10 embeds and 6,000 characters of embed text per message."""
    messages, cur, size = [], [], 0
    for e in embeds:
        s = embed_size(e)
        if len(e.get("description", "")) > 4096:
            raise SystemExit(f"Embed '{e.get('title')}' is over 4,096 characters; lower MAX_VIDEOS.")
        if cur and (size + s > 6000 or len(cur) == 10):
            messages.append(cur)
            cur, size = [], 0
        cur.append(e)
        size += s
    if cur:
        messages.append(cur)
    return messages


def send(url, embeds):
    body = json.dumps({"username": BOT_NAME, "embeds": embeds,
                       "allowed_mentions": {"parse": []}}).encode()
    for attempt in range(5):
        req = urllib.request.Request(
            url + ("&" if "?" in url else "?") + "wait=true", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "User-Agent": "PIRACY-stats (discord_report.py, 1.0)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status
        except urllib.error.HTTPError as err:
            if err.code == 429:
                wait = float(json.loads(err.read() or b"{}").get("retry_after", 2))
                time.sleep(wait + 0.5)
                continue
            raise SystemExit(f"Discord refused the report ({err.code}): {err.read()[:300]!r}")
    raise SystemExit("Discord kept rate-limiting the report; try again in a minute.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("posts", help="posts.json from the dashboard (or the tracker export)")
    ap.add_argument("--state", default="last_report.json", help="where the last report's numbers are kept")
    ap.add_argument("--dry-run", action="store_true", help="write the payload to --out instead of posting")
    ap.add_argument("--out", default="payload.json")
    ap.add_argument("--date", help="report date, YYYY-MM-DD (default today)")
    a = ap.parse_args()

    data = json.loads(pathlib.Path(a.posts).read_text(encoding="utf-8"))
    posts = data["rows"] if isinstance(data, dict) else data
    state_path = pathlib.Path(a.state)
    prev = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
    embeds, state = build(posts, prev, os.environ.get("DASHBOARD_URL") or None, a.date)
    messages = pack(embeds)

    if a.dry_run:
        pathlib.Path(a.out).write_text(json.dumps(
            [{"username": BOT_NAME, "embeds": m} for m in messages], ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"Dry run: {len(messages)} message(s), {len(embeds)} embeds -> {a.out}")
        return
    url = os.environ.get("DISCORD_STATS_WEBHOOK")
    if not url:
        raise SystemExit("Set DISCORD_STATS_WEBHOOK to the channel's webhook URL.")
    for m in messages:
        send(url, m)
        time.sleep(1)
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    print(f"Posted {len(messages)} message(s) to Discord and saved {state_path}.")


if __name__ == "__main__":
    main()
