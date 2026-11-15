"""Discord messages: the live scoreboard, alerts and check-ins, and the webhook calls."""
import json
import statistics

import sources
from discord_report import (ANSI_WHITE, BLUE, COLOURS, ESC, GRAY, GREEN, PLATFORMS, RED,
                            ansi, block, fmt_int, fmt_pct, n, stats)

BOT_NAME = "PIRACY Stats"
OUTBOX = None          # a list in dry runs: messages are collected instead of sent
SHORT = {name: short for name, short, _ in PLATFORMS}
COLOUR = {name: colour for name, _, colour in PLATFORMS}


# ------------------------------------------------------------------ webhook
def send(webhook, embeds, content=None):
    """Post a message; returns its id."""
    body = {"username": BOT_NAME, "embeds": embeds, "allowed_mentions": {"parse": []}}
    if content:
        body["content"] = content
    if OUTBOX is not None:
        OUTBOX.append({"action": "post", **body})
        return f"dry-{len(OUTBOX)}"
    r = sources.http("POST", webhook + "?wait=true", body=body)
    return (r or {}).get("id")


def edit(webhook, message_id, embeds):
    """Edit a message the webhook sent before. False if it was deleted."""
    body = {"embeds": embeds, "allowed_mentions": {"parse": []}}
    if OUTBOX is not None:
        OUTBOX.append({"action": "edit", "message_id": message_id, **body})
        return True
    try:
        sources.http("PATCH", f"{webhook}/messages/{message_id}", body=body)
        return True
    except sources.HTTPError as e:
        if e.status in (404, 403):
            return False
        raise


def pack(embeds):
    """Discord allows 10 embeds and 6,000 characters of embed text per message."""
    out, cur, size = [], [], 0
    for e in embeds:
        s = sum(len(str(e.get(k, ""))) for k in ("title", "description")) + len(
            e.get("footer", {}).get("text", "")) + len(e.get("author", {}).get("name", ""))
        if cur and (size + s > 5800 or len(cur) == 10):
            out.append(cur)
            cur, size = [], 0
        cur.append(e)
        size += s
    if cur:
        out.append(cur)
    return out


# ------------------------------------------------------------------ helpers
def delta(cur, prev):
    if cur is None or prev is None:
        return ""
    d = cur - prev
    if abs(d) < 0.5:
        return ansi("±0", GRAY)
    return ansi(f"{'▲' if d > 0 else '▼'} {d:+,.0f}", GREEN if d > 0 else RED, bold=True)


def vs_usual(value, usual):
    """'2.1× usual' in green, '0.6× usual' in red."""
    if value is None or not usual:
        return ansi("no baseline yet", GRAY)
    r = value / usual
    if 0.9 <= r <= 1.1:
        return ansi("about usual", GRAY)
    return ansi(f"{'▲' if r > 1 else '▼'} {r:.1f}× usual", GREEN if r > 1 else RED, bold=True)


def uk(t, fmt="%a %d %b, %H:%M"):
    return sources.parse_time(t).astimezone(sources.UK).strftime(fmt).replace(" 0", " ")


def links(posts):
    parts = [f"[{SHORT.get(p['platform'], p['platform'])}]({p['url']})" for p in posts if p.get("url")]
    return " · ".join(parts)


# ------------------------------------------------------------------ live scoreboard
def scoreboard(rows, videos, last_views, members, notes, now, dashboard_url=None, run_hours=3):
    """The message the bot keeps editing. rows: dashboard-style rows with a 'posted_at' time."""
    logged = [r for r in rows if n(r.get("views")) is not None]
    week = [r for r in logged if (now - sources.parse_time(r["posted_at"])).days < 7]
    a, w = stats(logged), stats(week)

    def line(label, key, f):
        return (f"{label:<11}{ansi(f(w[key]).rjust(7), ANSI_WHITE, bold=True)}"
                f"{ansi(f(a[key]).rjust(10), ANSI_WHITE, bold=True)}")

    total_now = a["views"] or 0
    total_before = (sum(v for k, v in last_views.items() if not k.startswith('_') and v is not None)
                    if last_views else None)
    lines = [ansi(f"{'':11}{'7 DAYS':>7}{'ALL TIME':>10}", GRAY),
             line("Views", "views", fmt_int) + "  " + delta(total_now, total_before),
             line("Follows", "follows", fmt_int),
             line("Engagement", "engagement_rate", fmt_pct),
             line("Shares", "shares", fmt_int)]
    if members is not None:
        was = last_views.get("_members") if last_views else None
        lines.append(f"{'Discord':<11}{ansi(fmt_int(members).rjust(7), ANSI_WHITE, bold=True)} members  "
                     + delta(members, was))
    head = {
        "color": COLOURS["overview"],
        "author": {"name": "PIRACY · Live stats"},
        "title": "Scoreboard",
        "description": (f"Updated **{uk(sources.iso(now))}** UK time. "
                        f"This message updates itself every {run_hours} hours.\n" + block(lines)),
    }
    if dashboard_url:
        head["url"] = dashboard_url

    # newest videos, one line of numbers per clip
    vlines = [ansi(f"{'':5}{'TIKTOK':>8}{'SHORTS':>8}{'REELS':>8}", GRAY)]
    order = sorted(videos.items(), key=lambda kv: kv[1]["first_posted"], reverse=True)[:6]
    for vid, info in order:
        cells, total, before = [], 0, 0
        for name, _, _ in PLATFORMS:
            ps = [r for r in logged if r["video_id"] == vid and r["platform"] == name]
            v = sum(n(r["views"]) or 0 for r in ps) if ps else None
            cells.append(ansi((fmt_int(v) if v is not None else "·").rjust(8),
                              ANSI_WHITE if v is not None else GRAY, bold=v is not None))
            for r in ps:
                total += n(r["views"]) or 0
                before += last_views.get(r["post_id"], 0) if last_views else (n(r["views"]) or 0)
        title = info["title"] if len(info["title"]) <= 30 else info["title"][:29].rstrip() + "…"
        vlines.append(f"{ansi(vid.ljust(5), COLOUR['TikTok'], bold=True)}{''.join(cells)}")
        vlines.append(f"  {ansi(title, GRAY)}  {delta(total, before) if last_views else ''}".rstrip())
    vids = {
        "color": COLOURS["videos"],
        "title": "Latest videos",
        "description": ("Views on each app, and the change since the last update.\n" + block(vlines))
        if order else "No videos tracked yet.",
    }
    right_now = {
        "color": COLOURS["notes"],
        "title": "Right now",
        "description": "\n".join(f"• {x}" for x in notes) if notes else "• Nothing needs attention.",
        "footer": {"text": "▲ up ▼ down since the last update · colours show on desktop"},
        "timestamp": sources.iso(now),
    }
    return [head, vids, right_now]


# ------------------------------------------------------------------ one-off messages
def new_video(vid, info, posts, now):
    lines = []
    for p in posts:
        age = (now - sources.parse_time(p["posted"])).total_seconds() / 3600
        when = f"{age / 24:.0f} days ago" if age >= 48 else f"{age:.0f} h ago" if age >= 1 else "just now"
        lines.append(f"**{p['platform']}** · posted {when} · "
                     f"{fmt_int(p.get('views'))} views so far")
    lk = links(posts)
    return [{
        "color": COLOURS["videos"],
        "author": {"name": "PIRACY · New video tracked"},
        "title": f"{vid} · {info['title']}",
        "description": "\n".join(lines) + (f"\n{lk}" if lk else "")
                       + f"\nFormat: {info.get('format') or 'not set'}. "
                       "Check-ins follow at 24 hours and 7 days.",
        "timestamp": sources.iso(now),
    }]


def check_in(vid, info, hours, per_platform, now):
    """per_platform: [(platform, snapshot dict, usual views or None, usual engagement or None)]"""
    label = "24-hour" if hours == 24 else "7-day" if hours == 168 else f"{hours}-hour"
    lines = [ansi(f"{'':8}{'VIEWS':>7}  VS YOUR USUAL", GRAY)]
    for name, snap, usual_views, _ in per_platform:
        lines.append(f"{ansi(SHORT[name].ljust(8), COLOUR[name], bold=True)}"
                     f"{ansi(fmt_int(snap.get('views')).rjust(7), ANSI_WHITE, bold=True)}  "
                     f"{vs_usual(snap.get('views'), usual_views)}")
        st = stats([snap])
        extra = [f"{fmt_pct(st['engagement_rate'])} eng"]
        if snap.get("follows") is not None:
            extra.append(f"{fmt_int(snap['follows'])} follows")
        if snap.get("full_watch_pct") is not None:
            extra.append(f"{fmt_pct(snap['full_watch_pct'])} full-watch")
        lines.append("  " + " · ".join(extra))
    return [{
        "color": COLOURS["platforms"],
        "author": {"name": f"PIRACY · {label} check-in"},
        "title": f"{vid} · {info['title']}",
        "description": block(lines),
        "footer": {"text": "Usual = the middle value of your other posts on that app at the same age"},
        "timestamp": sources.iso(now),
    }]


def taking_off(vid, info, post, hours, ratio, now):
    return [{
        "color": 0x3BA55C,
        "author": {"name": "PIRACY · Taking off"},
        "title": f"{vid} on {post['platform']}: {ratio:.1f}× your usual",
        "description": (f"**{fmt_int(post.get('views'))}** views about {hours:.0f} hours in. "
                        "Good moment to reply to comments, pin the Discord comment, "
                        "and get the follow-up clip ready.\n" + (links([post]) or "")).strip(),
        "timestamp": sources.iso(now),
    }]


def notice(title, text, now):
    return [{"color": COLOURS["notes"], "author": {"name": "PIRACY · Stats bot"}, "title": title,
             "description": text, "timestamp": sources.iso(now)}]


def recommendations_embed(recs):
    return {
        "color": 0x3BA55C,
        "title": "What to do next",
        "description": "\n".join(f"**{i}.** {r}" for i, r in enumerate(recs, 1))
        or "Not enough posts yet for solid advice.",
    }


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def dump_outbox(path):
    if OUTBOX is not None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(OUTBOX, f, ensure_ascii=False, indent=1)
