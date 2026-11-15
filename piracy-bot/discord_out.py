"""Discord messages: the live scoreboard, alerts and check-ins, and the webhook calls."""
import json
import statistics

import sources
from discord_report import COLOURS, PLATFORMS, SHORT, change, fmt_date, fmt_int, fmt_pct, n, pad_row, stats, tile, wavg

BOT_NAME = "PIRACY Stats"
OUTBOX = None          # a list in dry runs: messages are collected instead of sent


# ------------------------------------------------------------------ webhook
def send(webhook, embeds, content=None, thread_name=None, full=False):
    """Post a message; returns its id (or the whole message with full=True)."""
    body = {"username": BOT_NAME, "embeds": tidy(embeds), "allowed_mentions": {"parse": []}}
    if content:
        body["content"] = content
    if thread_name:
        body["thread_name"] = thread_name     # creates a new post in a forum channel
    if OUTBOX is not None:
        OUTBOX.append({"action": "post", **body})
        msg = {"id": f"dry-{len(OUTBOX)}", "channel_id": f"dry-{len(OUTBOX)}"}
    else:
        msg = sources.http("POST", webhook + "?wait=true", body=body) or {}
    return msg if full else msg.get("id")


def edit(webhook, message_id, embeds, thread_id=None):
    """Edit a message the webhook sent before. False if it was deleted."""
    body = {"embeds": tidy(embeds), "allowed_mentions": {"parse": []}}
    if OUTBOX is not None:
        OUTBOX.append({"action": "edit", "message_id": message_id, "thread_id": thread_id, **body})
        return True
    url = f"{webhook}/messages/{message_id}" + (f"?thread_id={thread_id}" if thread_id else "")
    try:
        sources.http("PATCH", url, body=body)
        return True
    except sources.HTTPError as e:
        if e.status in (400, 403, 404):   # gone, or not a message this webhook can edit
            return False
        raise


def tidy(embeds):
    """Discord refuses a message if any field name or value is empty."""
    for e in embeds:
        for f in e.get("fields", []):
            f["name"] = (f.get("name") or "\u200b")[:256]
            f["value"] = (f.get("value") or "\u200b")[:1024]
    return embeds


def size(e):
    s = sum(len(str(e.get(k, ""))) for k in ("title", "description"))
    s += len(e.get("footer", {}).get("text", "")) + len(e.get("author", {}).get("name", ""))
    return s + sum(len(f["name"]) + len(f["value"]) for f in e.get("fields", []))


def pack(embeds):
    """Discord allows 10 embeds and 6,000 characters of embed text per message."""
    out, cur, total = [], [], 0
    for e in embeds:
        s = size(e)
        if cur and (total + s > 5800 or len(cur) == 10):
            out.append(cur)
            cur, total = [], 0
        cur.append(e)
        total += s
    if cur:
        out.append(cur)
    return out


# ------------------------------------------------------------------ helpers
def vs_usual(value, usual):
    if value is None or not usual:
        return "no comparison yet"
    r = value / usual
    if 0.9 <= r <= 1.1:
        return "about your usual"
    return f"🟢 {r:.1f}× your usual" if r > 1 else f"🔴 {r:.1f}× your usual"


def uk(t, fmt="%a %d %b, %H:%M"):
    return sources.parse_time(t).astimezone(sources.UK).strftime(fmt).replace(" 0", " ")


def ago(posted, now):
    h = (now - sources.parse_time(posted)).total_seconds() / 3600
    return f"{h / 24:.0f} days ago" if h >= 48 else f"{h:.0f} h ago" if h >= 1 else "just now"


# ------------------------------------------------------------------ live scoreboard
def scoreboard(rows, videos, last_views, members, notes, now, dashboard_url=None, run_hours=3, tab_links=None):
    """The message the bot keeps editing."""
    logged = [r for r in rows if n(r.get("views")) is not None]
    week = [r for r in logged if (now - sources.parse_time(r["posted_at"])).days < 7]
    a, w = stats(logged), stats(week)
    # only posts that are still public: a private or deleted video doesn't count as a drop
    total_before = sum(last_views.get(r["post_id"], 0) or 0 for r in logged) if last_views else None
    fields = [
        tile("Views", fmt_int(w["views"])),
        tile("Follows", fmt_int(w["follows"])),
        tile("Engagement", fmt_pct(w["engagement_rate"])),
        tile("Shares", fmt_int(w["shares"])),
        tile("Views, all time", fmt_int(a["views"]),
             change(a["views"], total_before) if total_before is not None else ""),
    ]
    if members is not None:
        was = last_views.get("_members") if last_views else None
        fields.append(tile("Discord members", fmt_int(members), change(members, was) if was is not None else ""))
    head = {
        "color": COLOURS["overview"],
        "author": {"name": "PIRACY · Live stats"},
        "title": "Scoreboard",
        "description": (f"Updated **{uk(sources.iso(now))}** UK time · refreshes every {run_hours} hours\n"
                        + (("**Tabs:** " + "  ·  ".join(f"[{k}]({v})" for k, v in tab_links.items()) + "\n")
                           if tab_links else "")
                        + "*Last 7 days, unless it says otherwise*"),
        "fields": pad_row(fields),
    }
    if dashboard_url:
        head["url"] = dashboard_url

    vfields = []
    order = sorted(videos.items(), key=lambda kv: kv[1]["first_posted"], reverse=True)[:5]
    for vid, info in order:
        parts, total, before = [], 0, 0
        for name, short in PLATFORMS:
            ps = [r for r in logged if r["video_id"] == vid and r["platform"] == name]
            if not ps:
                continue
            v = sum(n(r["views"]) or 0 for r in ps)
            parts.append(f"{short} **{fmt_int(v)}**")
            total += v
            before += sum(last_views.get(r["post_id"], 0) for r in ps) if last_views else v
        line = "  ·  ".join(parts)
        if last_views:
            line += f"   {change(total, before)}"
        vfields.append({"name": f"{vid} · {info['title']}", "value": line or "No numbers yet"})
    vids = {"color": COLOURS["videos"], "title": "Latest videos",
            "fields": vfields or [{"name": "​", "value": "No videos tracked yet."}]}
    right_now = {
        "color": COLOURS["notes"],
        "title": "Right now",
        "description": "\n".join(f"• {x}" for x in notes) if notes else "• Nothing needs attention.",
        "footer": {"text": "🟢 up · 🔴 down · changes are since the last update"},
        "timestamp": sources.iso(now),
    }
    return [head, vids, right_now]


# ------------------------------------------------------------------ one-off messages
def new_video(vid, info, posts, now):
    fields = []
    for p in posts:
        lines = [f"**{fmt_int(p.get('views'))}** views", f"posted {ago(p['posted'], now)}"]
        if p.get("url"):
            lines.append(f"[Open]({p['url']})")
        fields.append({"name": SHORT.get(p["platform"], p["platform"]), "value": "\n".join(lines), "inline": True})
    return [{
        "color": COLOURS["videos"],
        "author": {"name": "PIRACY · New video tracked"},
        "title": f"{vid} · {info['title']}",
        "description": f"*{info.get('format') or 'Format not set'} · check-ins at 24 hours and 7 days*",
        "fields": pad_row(fields),
        "timestamp": sources.iso(now),
    }]


def check_in(vid, info, hours, per_platform, now):
    """per_platform: [(platform, snapshot dict, usual views or None, unused)]"""
    label = "24-hour" if hours == 24 else "7-day" if hours == 168 else f"{hours}-hour"
    fields = []
    for name, snap, usual_views, _ in per_platform:
        st = stats([snap])
        lines = [f"**{fmt_int(snap.get('views'))}** views", vs_usual(snap.get("views"), usual_views),
                 f"{fmt_pct(st['engagement_rate'])} engagement"]
        if snap.get("follows") is not None:
            lines.append(f"{fmt_int(snap['follows'])} follows")
        if snap.get("full_watch_pct") is not None:
            lines.append(f"{fmt_pct(snap['full_watch_pct'])} full-watch")
        fields.append({"name": SHORT[name], "value": "\n".join(lines), "inline": True})
    return [{
        "color": COLOURS["platforms"],
        "author": {"name": f"PIRACY · {label} check-in"},
        "title": f"{vid} · {info['title']}",
        "fields": pad_row(fields),
        "footer": {"text": "Your usual = the middle value of your other posts on that app at the same age"},
        "timestamp": sources.iso(now),
    }]


def taking_off(vid, info, post, hours, ratio, now):
    link = f"\n[Open it]({post['url']})" if post.get("url") else ""
    return [{
        "color": COLOURS["advice"],
        "author": {"name": "PIRACY · Taking off"},
        "title": f"{vid} on {SHORT.get(post['platform'], post['platform'])}: {ratio:.1f}× your usual",
        "description": (f"**{fmt_int(post.get('views'))}** views about {hours:.0f} hours in.\n"
                        f"Good moment to reply to comments, pin the Discord comment and get the "
                        f"follow-up clip ready.{link}"),
        "timestamp": sources.iso(now),
    }]


def notice(title, text, now):
    return [{"color": COLOURS["notes"], "author": {"name": "PIRACY · Stats bot"}, "title": title,
             "description": text, "timestamp": sources.iso(now)}]


def recommendations_embed(recs):
    return {
        "color": COLOURS["advice"],
        "title": "What to do next",
        "description": "\n\n".join(f"**{i}.** {r}" for i, r in enumerate(recs, 1))
        or "Not enough posts yet for solid advice. It starts once there are a few posts on each app.",
    }


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def dump_outbox(path):
    if OUTBOX is not None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(OUTBOX, f, ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ one tab per app (forum posts)
TAB_NAMES = {"TikTok": "🎵 TikTok", "YouTube Shorts": "▶️ YouTube Shorts", "Instagram Reels": "📸 Instagram Reels"}
TAB_COLOURS = {"TikTok": 0x25F4EE, "YouTube Shorts": 0xFF0033, "Instagram Reels": 0xD62976}


def platform_tab(name, rows, last_views, now, back_link=None, empty_note=None, run_hours=3):
    mine = [r for r in rows if r["platform"] == name and n(r.get("views")) is not None]
    week = [r for r in mine if (now - sources.parse_time(r["posted_at"])).days < 7]
    a, w = stats(mine), stats(week)
    desc = f"Updated **{uk(sources.iso(now))}** UK time · refreshes every {run_hours} hours"
    if back_link:
        desc += f"\n[← Back to the scoreboard]({back_link})"
    head = {"color": TAB_COLOURS[name], "author": {"name": "PIRACY · Live stats"},
            "title": TAB_NAMES[name], "description": desc, "timestamp": sources.iso(now)}
    if not mine:
        head["description"] += "\n\n" + (empty_note or f"No {name} posts found yet.")
        return [head]

    before = sum(last_views.get(r["post_id"], 0) or 0 for r in mine) if last_views else None
    fields = [
        tile("Views (7 days)", fmt_int(w["views"])),
        tile("Views (all time)", fmt_int(a["views"]), change(a["views"], before) if before is not None else ""),
        tile("Posts", str(a["posts"]), sub=f"{fmt_int(a['avg_views'])} views each"),
        tile("Engagement", fmt_pct(a["engagement_rate"])),
        tile("Likes", fmt_int(a["likes"])),
        tile("Comments", fmt_int(a["comments"])),
    ]
    for label, key in (("Shares", "shares"), ("Saves", "saves"), ("Follows", "follows")):
        if a[key] is not None:
            fields.append(tile(label, fmt_int(a[key])))
    if a["full_watch_pct"] is not None:
        fields.append(tile("Stayed to watch" if name == "YouTube Shorts" else "Full-watch", fmt_pct(a["full_watch_pct"])))
    avg_watch = wavg(mine, "avg_watch_s")
    if avg_watch is not None:
        fields.append(tile("Average watch", f"{avg_watch:.1f} s"))
    skips = [r["skip_rate"] for r in mine if r.get("skip_rate") is not None]
    if skips:
        fields.append(tile("Swiped away", fmt_pct(sum(skips) / len(skips)), sub="in the first seconds"))
    head["fields"] = pad_row(fields)

    pfields = []
    for r in sorted(mine, key=lambda r: r["posted_at"], reverse=True)[:15]:
        chg = change(n(r["views"]), last_views.get(r["post_id"])) if last_views else ""
        st = stats([r])
        line = f"**{fmt_int(st['views'])}** views  {chg}  ·  {fmt_pct(st['engagement_rate'])} eng".replace("  ·", " ·")
        extra = [f"posted {fmt_date(r['posted'], False)}"]
        if r.get("source") == "typed in" and r.get("snapshot") not in (None, "live"):
            extra.append(f"numbers from {r['snapshot']}")
        if r.get("url"):
            extra.append(f"[Open]({r['url']})")
        pfields.append({"name": f"{r['video_id']} · {r['video']}", "value": line + "\n" + " · ".join(extra)})
    posts = {"color": TAB_COLOURS[name], "title": "Every post, newest first", "fields": pfields,
             "footer": {"text": "🟢 up · 🔴 down · changes are since the last update"}}
    return [head, posts]
