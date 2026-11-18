"""Discord: the live scoreboard, alerts and the weekly report, built with Discord's
newer message layout ("Components V2": cards, sections, image galleries and link buttons),
sent through the existing webhook.

Ordinary webhooks can send these layouts but not clickable menus, so buttons here are
links into the website. In shadow mode nothing is sent: messages go to data/outbox.json.
"""
import time

from . import net, util

V2 = 1 << 15            # the IS_COMPONENTS_V2 message flag
BOT_NAME = "PIRACY Stats"
ACCENT = {"youtube": 0xFF6B6B, "tiktok": 0x2EC4B6, "instagram": 0xC792EA, "discord": 0x8EA1FF,
          "board": 0x2EC4B6, "gold": 0xE3B04B, "warn": 0xF5A623, "bad": 0xE5484D, "good": 0x3DD68C}
ICON = {"youtube": "▶️", "tiktok": "🎵", "instagram": "📸", "discord": "💬"}
STATUS_DOT = {"ok": "🟢", "typed": "🟡", "error": "🔴", "stale": "🟠", "not_connected": "⚪"}


# ------------------------------------------------------------------ building blocks
def text(s):
    return {"type": 10, "content": s}


def sep(big=False, line=True):
    return {"type": 14, "divider": line, "spacing": 2 if big else 1}


def thumb(url, desc=None):
    t = {"type": 11, "media": {"url": url}}
    if desc:
        t["description"] = desc[:256]
    return t


def section(texts, accessory):
    return {"type": 9, "components": [text(t) for t in texts][:3], "accessory": accessory}


def gallery(urls):
    return {"type": 12, "items": [{"media": {"url": u}} for u in urls][:10]}


def link(label, url, emoji=None):
    b = {"type": 2, "style": 5, "label": label[:80], "url": url}
    if emoji:
        b["emoji"] = {"name": emoji}
    return b


def row(buttons):
    return {"type": 1, "components": buttons[:5]}


def card(children, color):
    return {"type": 17, "accent_color": color, "components": [c for c in children if c]}


def ts(t, style="R"):
    return f"<t:{int(util.parse(t).timestamp())}:{style}>"


# ------------------------------------------------------------------ checking a message before sending
def count(components):
    n = 0
    for c in components:
        n += 1
        n += count(c.get("components", []))
        if c.get("accessory"):
            n += 1
    return n


def text_length(components):
    total = 0
    for c in components:
        if c.get("type") == 10:
            total += len(c["content"])
        total += text_length(c.get("components", []))
        if c.get("accessory", {}).get("type") == 10:
            total += len(c["accessory"]["content"])
    return total


def validate(components):
    """Raise ValueError if Discord would refuse the message."""
    if count(components) > 40:
        raise ValueError(f"{count(components)} components (Discord allows 40)")
    if text_length(components) > 4000:
        raise ValueError(f"{text_length(components)} characters of text (Discord allows 4000)")

    def walk(cs):
        for c in cs:
            t = c.get("type")
            if t == 1 and not (1 <= len(c["components"]) <= 5):
                raise ValueError("a button row needs 1 to 5 buttons")
            if t == 2:
                if not c.get("url", "").startswith("https://"):
                    raise ValueError(f"button link must be https: {c.get('url')}")
                if not 1 <= len(c.get("label", "")) <= 80:
                    raise ValueError("button label length")
            if t == 9 and not 1 <= len(c["components"]) <= 3:
                raise ValueError("a section needs 1 to 3 texts")
            if t == 10 and not c["content"].strip():
                raise ValueError("empty text")
            if t == 11 and not c["media"]["url"].startswith(("https://", "attachment://")):
                raise ValueError("thumbnail url")
            if t == 12 and not 1 <= len(c["items"]) <= 10:
                raise ValueError("gallery needs 1 to 10 images")
            walk(c.get("components", []))
            if c.get("accessory"):
                walk([c["accessory"]])
    walk(components)
    return True


# ------------------------------------------------------------------ sending
class Discord:
    def __init__(self, webhook, live, outbox=None):
        self.webhook = (webhook or "").strip()
        self.live = bool(live and self.webhook)
        self.outbox = outbox if outbox is not None else []
        self.sent = 0

    def _url(self, path="", thread_id=None, wait=True):
        q = ["with_components=true"]
        if wait:
            q.append("wait=true")
        if thread_id:
            q.append(f"thread_id={thread_id}")
        return f"{self.webhook}{path}?{'&'.join(q)}"

    def _payload(self, components, files, extra=None):
        validate(components)
        body = {"username": BOT_NAME, "flags": V2, "components": components, "allowed_mentions": {"parse": []}}
        if files:
            body["attachments"] = [{"id": i, "filename": name} for i, (name, _) in enumerate(files)]
        body.update(extra or {})
        return body

    def _files(self, files):
        return [(f"files[{i}]", name, blob, "image/png") for i, (name, blob) in enumerate(files or [])] or None

    def send(self, components, files=None, thread_name=None, kind="message"):
        body = self._payload(components, files, {"thread_name": thread_name} if thread_name else None)
        if not self.live:
            self.outbox.append({"action": "send", "kind": kind, "body": body,
                                "files": [n for n, _ in files or []]})
            return {"id": f"shadow-{len(self.outbox)}", "channel_id": f"shadow-{len(self.outbox)}"}
        r = net.request("POST", self._url(), json_body=body, files=self._files(files))
        self.sent += 1
        time.sleep(0.4)
        return r or {}

    def edit(self, message_id, components, files=None, thread_id=None, kind="edit"):
        """True if edited; False if the message is gone (deleted, or not one this webhook can edit)."""
        if not str(message_id or "").isdigit():
            return False
        body = self._payload(components, files, {"content": None, "embeds": None})
        body.pop("username", None)
        if not self.live:
            self.outbox.append({"action": "edit", "kind": kind, "message_id": message_id, "body": body,
                                "files": [n for n, _ in files or []]})
            return True
        try:
            net.request("PATCH", self._url(f"/messages/{message_id}", thread_id, wait=False),
                        json_body=body, files=self._files(files))
            self.sent += 1
            time.sleep(0.4)
            return True
        except net.HTTPError as e:
            if e.status in (400, 403, 404):
                return False
            raise

    def delete(self, message_id, thread_id=None):
        if not self.live or not str(message_id or "").isdigit():
            return
        try:
            net.request("DELETE", self._url(f"/messages/{message_id}", thread_id, wait=False))
        except net.HTTPError:
            pass


# ------------------------------------------------------------------ the messages
def _app_line(pl, s, status, acc):
    name, icon = util.NAMES[pl], ICON[pl]
    dot = STATUS_DOT.get(status, "⚪")
    if not s or not s.get("posts"):
        if status == "not_connected":
            return f"{dot} **{icon} {name}** · not connected yet"
        if status == "error":
            return f"{dot} **{icon} {name}** · couldn't read it this time"
        return f"{dot} **{icon} {name}** · no posts yet"
    parts = [f"`{util.fmt_int(s.get('total_views'))}` views"]
    if s.get("gain_24h") is not None and not s.get("typed"):
        parts.append(f"**{util.fmt_signed(s['gain_24h'])}** in 24 h")
    parts.append(f"{s['posts']} post{'s' if s['posts'] != 1 else ''}")
    f = (acc or {}).get("followers")
    if f is not None:
        word = "subscribers" if pl == "youtube" else "followers"
        parts.append(f"{util.fmt_int(f)} {word}")
    tail = ""
    if status == "typed":
        tail = " · *typed in*"
    elif status in ("error", "stale"):
        tail = " · *last good numbers*"
    return f"{dot} **{icon} {name}** · " + " · ".join(parts) + tail


def site_buttons(site, page=None):
    if not site:
        return None
    base = site.rstrip("/") + "/"
    return row([link("Dashboard", base, "🌊"), link("Videos", base + "#videos", "🎬"),
                link("Analytics", base + "#analytics", "📈"), link("Research", base + "#research", "🧪"),
                link("Roblox trends", base + "#trends", "🔥")])


def scoreboard(ctx):
    """ctx: summary, statuses, accounts, top (list of rows), notes, now, site, avatar, chart (attachment name)."""
    s, st = ctx["summary"], ctx["statuses"]
    head = [f"## 🏴‍☠️ PIRACY · Live stats",
            f"Updated {ts(ctx['now'])} · refreshes every hour"]
    blocks = [section(head, thumb(ctx["avatar"], "PIRACY")) if ctx.get("avatar") else text("\n".join(head)),
              sep()]
    lines = [_app_line(pl, s["platforms"].get(pl), st.get(pl, "not_connected"), ctx["accounts"].get(pl))
             for pl in util.PLATFORMS]
    d = s.get("discord")
    if d and d.get("members") is not None:
        extra = f" · {util.fmt_signed(d['members_7d'])} this week" if d.get("members_7d") else ""
        lines.append(f"🟢 **💬 Discord** · `{util.fmt_int(d['members'])}` members{extra}")
    blocks.append(text("\n".join(lines)))
    if ctx.get("chart"):
        blocks.append(gallery([f"attachment://{ctx['chart']}"]))
    blocks.append(sep())
    if ctx.get("top"):
        medals = ["🥇", "🥈", "🥉"]
        tl = ["### 🏆 Top this week"]
        for i, r in enumerate(ctx["top"][:3]):
            t = util.md_escape(util.clean_title(r["title"], 52))
            name = f"[{t}]({r['url']})" if r.get("url") else t
            g = ""
            if r.get("gain") and abs(r["gain"] - r["views"]) >= 1:
                g = f" · {util.fmt_signed(r['gain'])} this week"
            elif r.get("gain"):
                g = " · new this week"
            tl.append(f"{medals[i]} {name} · {util.SHORT[r['platform']]} · **{util.fmt_int(r['views'])}** views{g}")
        blocks.append(text("\n".join(tl)))
    if ctx.get("notes"):
        blocks.append(text("### 🧭 Ship's log\n" + "\n".join(f"• {n}" for n in ctx["notes"][:3])))
    if ctx.get("next"):
        blocks.append(text(ctx["next"]))
    blocks.append(text("-# Apps count views differently, so they're never added together. "
                       "🟢 live · 🟡 typed in · 🟠 last good numbers · ⚪ not connected"))
    msg = [card(blocks, ACCENT["board"])]
    btn = site_buttons(ctx.get("site"))
    if btn:
        msg.append(btn)
    return msg


def new_post(p, group, base, site):
    pl = p["platform"]
    bits = [f"### 🆕 New on {util.NAMES[pl]}"]
    t = util.md_escape(util.clean_title(p.get("title"), 90))
    bits.append(f"**[{t}]({p['url']})**" if p.get("url") else f"**{t}**")
    meta = []
    if group:
        meta.append(group)
    if p.get("duration_s"):
        meta.append(f"{p['duration_s']:.0f} s")
    meta.append(f"posted {ts(p['posted'])}")
    bits.append(" · ".join(meta))
    lines = []
    if base and base.get(24):
        lines.append(f"Your usual at 24 hours on {util.SHORT[pl]}: **{util.fmt_int(base[24]['median'])}** views "
                     f"(middle of {base[24]['n']} posts). I'll check in at 24 hours and 7 days.")
    else:
        lines.append("I'll check in at 24 hours and 7 days.")
    comps = [section(bits, thumb(p["thumb"])) if p.get("thumb") else text("\n".join(bits)), text("\n".join(lines))]
    buttons = []
    if p.get("url"):
        buttons.append(link("Watch", p["url"], "▶️"))
    if site:
        buttons.append(link("Video page", site.rstrip("/") + f"/#video={p['id']}", "📊"))
    out = [card(comps, ACCENT.get(pl, ACCENT["board"]))]
    if buttons:
        out.append(row(buttons))
    return out


def milestone(m, nxt, site):
    lines = [f"## 🏆 Milestone!", f"**{m['label']}**", f"Reached {ts(m['ts'], 'f')}"]
    if nxt:
        lines.append(f"Next stop: **{util.fmt_int(nxt['next'])}** · {nxt['pct'] * 100:.0f}% of the way there")
    out = [card([text("\n".join(lines))], ACCENT["gold"])]
    if site:
        out.append(row([link("See the treasure map", site.rstrip("/") + "/#overview", "🗺️")]))
    return out


def take_off(p, hours, ratio, base_n, median, site):
    t = util.md_escape(util.clean_title(p.get("title"), 80))
    name = f"[{t}]({p['url']})" if p.get("url") else t
    lines = [f"### 🚀 Taking off on {util.NAMES[p['platform']]}",
             f"**{name}** is at **{ratio:.1f}×** your usual after {hours} hours",
             f"{util.fmt_int(p['metrics'].get('views'))} views · your usual is {util.fmt_int(median)} (middle of {base_n} posts)",
             "Good moment to reply to comments, pin the Discord link and line up a follow-up clip."]
    comps = [section(lines, thumb(p["thumb"])) if p.get("thumb") else text("\n".join(lines))]
    out = [card(comps, ACCENT["good"])]
    if site:
        out.append(row([link("Video page", site.rstrip("/") + f"/#video={p['id']}", "📊")]))
    return out


def check_in(p, hours, value, base, site):
    label = "24-hour" if hours == 24 else "7-day" if hours == 168 else f"{hours}-hour"
    t = util.md_escape(util.clean_title(p.get("title"), 80))
    name = f"[{t}]({p['url']})" if p.get("url") else t
    m = p.get("metrics", {})
    lines = [f"### ⏱️ {label} check-in · {util.NAMES[p['platform']]}", f"**{name}**",
             f"**{util.fmt_int(value)}** views · {util.fmt_int(m.get('likes'))} likes · {util.fmt_int(m.get('comments'))} comments"]
    b = (base or {}).get(hours)
    if b:
        r = value / b["median"] if b["median"] else None
        if r:
            word = "above" if r >= 1.15 else "below" if r <= 0.85 else "about"
            lines.append(f"{'🟢' if r >= 1.15 else '🔴' if r <= 0.85 else '⚪'} {word} your usual "
                         f"({r:.1f}× the middle of {b['n']} posts: {util.fmt_int(b['median'])})")
    else:
        lines.append("-# Comparisons start once there are 3 earlier posts on this app.")
    comps = [section(lines[:3], thumb(p["thumb"])) if p.get("thumb") else text("\n".join(lines[:3]))]
    if len(lines) > 3:
        comps.append(text("\n".join(lines[3:])))
    out = [card(comps, ACCENT.get(p["platform"], ACCENT["board"]))]
    if site:
        out.append(row([link("Video page", site.rstrip("/") + f"/#video={p['id']}", "📊")]))
    return out


def health(platform, message, fixed=False):
    if fixed:
        return [card([text(f"### ✅ {util.NAMES.get(platform, platform)} is back\nNumbers are updating again.")],
                     ACCENT["good"])]
    return [card([text(f"### ⚠️ {util.NAMES.get(platform, platform)} needs a look\n{message}\n"
                       "-# Until it's fixed, the scoreboard keeps the last good numbers. I'll say when it's back.")],
                 ACCENT["warn"])]


def weekly(ctx):
    s, now = ctx["summary"], ctx["now"]
    lines = [f"## 📅 Weekly report · week to {util.uk(now):%a %-d %b}"]
    for pl in util.PLATFORMS:
        p = s["platforms"].get(pl) or {}
        if not p.get("posts"):
            continue
        rows = p.get("daily", [])[-14:]
        this = sum(v for _, v in rows[-7:] if v) if rows else None
        prev_vals = [v for _, v in rows[:-7] if v is not None]
        prev = sum(prev_vals) if len(prev_vals) == 7 else None
        bit = f"{ICON[pl]} **{util.NAMES[pl]}** · **{util.fmt_signed(this)}** views this week"
        if prev:
            bit += f" (last week {util.fmt_signed(prev)})"
        f7 = p.get("followers_7d")
        if f7:
            bit += f" · {util.fmt_signed(f7)} {'subscribers' if pl == 'youtube' else 'followers'}"
        lines.append(bit)
    d = s.get("discord")
    if d and d.get("members_7d") is not None:
        lines.append(f"💬 **Discord** · {util.fmt_signed(d['members_7d'])} members ({util.fmt_int(d['members'])} now)")
    blocks = [text("\n".join(lines))]
    if ctx.get("chart"):
        blocks.append(gallery([f"attachment://{ctx['chart']}"]))
    if ctx.get("top"):
        tl = ["### 🏆 Best of the week"]
        for i, r in enumerate(ctx["top"][:3], 1):
            t = util.md_escape(util.clean_title(r["title"], 52))
            tl.append(f"{i}. [{t}]({r['url']}) · {util.SHORT[r['platform']]} · {util.fmt_int(r['views'])} views")
        blocks.append(text("\n".join(tl)))
    if ctx.get("experiments"):
        el = ["### 🧪 Try next"]
        for e in ctx["experiments"][:2]:
            el.append(f"**{e['title']}** · {e['test']}\n-# Why: {e['evidence']}")
        blocks.append(text("\n".join(el)))
    scan = ctx.get("scan") or {}
    if scan.get("top"):
        sl = ["### 🔭 What's working for other Roblox devs"]
        for st in scan.get("stats", [])[:2]:
            sl.append(f"• {st['label']}: **{st['value']}** ({st['detail']})")
        for r in scan["top"][:3]:
            t = util.md_escape(util.clean_title(r["title"], 50))
            sl.append(f"▸ [{t}]({r['url']}) · {util.fmt_short(r['per_day'])} views/day · {r['duration_s']} s")
        blocks.append(text("\n".join(sl)))
    tb = (ctx.get("trends") or {}).get("rows") or []
    if tb:
        tl = ["### 🔥 Roblox right now (trend bot)"]
        for r in tb[:3]:
            tl.append(f"▸ **{util.md_escape(r['name'][:40])}** · {util.fmt_short(r['players'])} players · score {r['score']:.0f}")
        sea = [r for r in tb if r["sea"]][:2]
        for r in sea:
            tl.append(f"🌊 Sea/pirate on the board: **{util.md_escape(r['name'][:40])}** · {util.fmt_short(r['players'])} players")
        blocks.append(text("\n".join(tl)))
    msg = [card(blocks, ACCENT["gold"])]
    btn = site_buttons(ctx.get("site"))
    if btn:
        msg.append(btn)
    return msg


def platform_tab(pl, rows, summary, status, acc, now, site):
    s = summary["platforms"].get(pl) or {}
    head = [f"## {ICON[pl]} {util.NAMES[pl]}", f"Updated {ts(now)} · {_app_line(pl, s, status, acc)}"]
    blocks = [text("\n".join(head)), sep()]
    mine = [r for r in rows if r["platform"] == pl and r["status"] == "live"][:8]
    if not mine:
        blocks.append(text("No posts tracked yet." if status == "ok" else
                           "Not connected yet: see the Status page on the dashboard."))
    for r in mine:
        t = util.md_escape(util.clean_title(r["title"], 60))
        name = f"[{t}]({r['url']})" if r.get("url") else t
        m = r["metrics"]
        line = f"**{name}**\n`{util.fmt_int(m.get('views'))}` views"
        if r.get("gain_24h"):
            line += f" · {util.fmt_signed(r['gain_24h'])} in 24 h"
        line += f" · {util.fmt_int(m.get('likes'))} likes · posted {ts(r['posted'], 'd')}"
        if r.get("vs_usual"):
            v = r["vs_usual"]
            line += f" · {v['ratio']:.1f}× usual at {v['hours']} h"
        blocks.append(text(line))
    msg = [card(blocks, ACCENT[pl])]
    if site:
        msg.append(row([link("All videos", site.rstrip("/") + f"/#videos?app={pl}", "🎬"),
                        link("Dashboard", site.rstrip("/") + "/", "🌊")]))
    return msg
