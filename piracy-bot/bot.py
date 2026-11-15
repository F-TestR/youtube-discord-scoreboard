#!/usr/bin/env python3
"""PIRACY stats bot.

Runs every few hours (GitHub Actions). Each run it:
  1. collects numbers: YouTube Shorts (API key), Instagram Reels (token, optional),
     and anything typed into manual/posts.csv (TikTok for now);
  2. groups the TikTok, Short and Reel of the same clip into one video (V00, V01...);
  3. posts to Discord: new-video alerts, 24-hour and 7-day check-ins, "taking off"
     alerts, and edits one live scoreboard message;
  4. on Mondays posts the weekly report with recommendations and a scan of what's
     working in other Roblox dev Shorts;
  5. saves its memory in data/ and writes data/posts.json for the analytics dashboard.

Secrets come from environment variables (GitHub secrets): DISCORD_STATS_WEBHOOK,
YOUTUBE_API_KEY, and optionally INSTAGRAM_TOKEN and DISCORD_BOT_TOKEN.
Without DISCORD_STATS_WEBHOOK, or with DRY_RUN=1, messages go to data/outbox.json.
"""
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import statistics
import sys
import traceback

import discord_out as D
import discord_report
import recommend
import scanner
import sources

HERE = pathlib.Path(__file__).resolve().parent
DATA = pathlib.Path(os.environ.get("BOT_DATA") or HERE / "data")
MILESTONES = [3, 6, 12, 24, 48, 168, 720]
METRICS = ["views", "likes", "comments", "shares", "saves", "follows", "avg_watch_s",
           "full_watch_pct", "skip_rate", "reach"]
FORMAT_WORDS = {
    "Cinematic": ["cutscene", "cinematic", "trailer", "teaser", "intro", "opening"],
    "Gameplay": ["gameplay", "battle", "combat", "fight", "storm", "sailing", "pvp", "raid", "boss"],
    "Devlog / behind the scenes": ["devlog", "update", "behind", "making", "how we", "progress", "wip"],
}
STOP = scanner.STOP | {"pov", "your", "when", "crew", "plan", "was", "you", "they", "out"}


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def words(text):
    text = re.sub(r"#(\w+)", r"\1", (text or "").lower())
    return {w for w in re.findall(r"[a-z]{3,}", text) if w not in STOP}


def clean_title(t):
    t = re.sub(r"#\w+", "", t or "")
    t = re.sub(r"[^\w\s'’:!?,.()&-]", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -:")
    return (t[:57] + "…") if len(t) > 58 else (t or "Untitled")


def guess_format(text):
    text = (text or "").lower()
    for fmt, keys in FORMAT_WORDS.items():
        if any(k in text for k in keys):
            return fmt
    return None


def label_hours(label):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|d|day|days)\b", (label or "").lower())
    if not m:
        return None
    x = float(m.group(1))
    return int(round(x * 24 if m.group(2).startswith("d") else x))


# ------------------------------------------------------------------ grouping clips
GROUPING_VERSION = 2


def assign_videos(posts, state, links):
    if state.get("grouping_version") != GROUPING_VERSION:
        # earlier versions could give a typed-in video_id to a different clip: regroup once
        state["video_of"], state["videos"] = {}, {}
        state["grouping_version"] = GROUPING_VERSION
    video_of = state.setdefault("video_of", {})
    videos = state.setdefault("videos", {})
    taken = {(video_of[p["post_id"]], p["platform"]) for p in posts if p["post_id"] in video_of}

    def override(p):
        return links.get(p["post_id"]) or (links.get(p["url"]) if p.get("url") else None) or links.get(p["title"]) or {}

    reserved = {override(p).get("video_id") or p.get("video_id") for p in posts} - {None, ""}

    def next_id():
        ids = [int(v[1:]) for v in set(videos) | reserved if re.fullmatch(r"V\d+", v)]
        return f"V{(max(ids) + 1) if ids else 0:02d}"

    # posts with a video_id typed in go first, so the other apps' copies can match them
    ordered = sorted(posts, key=lambda p: (not (override(p).get("video_id") or p.get("video_id")), p["posted"]))
    for p in ordered:
        pid = p["post_id"]
        ov = override(p)
        want = ov.get("video_id") or p.get("video_id")
        if want:
            video_of[pid] = want
        if pid not in video_of:
            t = sources.parse_time(p["posted"])
            best, best_score = None, 0.0
            for vid, info in videos.items():
                if (vid, p["platform"]) in taken:
                    continue
                gap = abs((t - sources.parse_time(info["first_posted"])).total_seconds()) / 3600
                if gap > 72:
                    continue
                a, b = words(p["title"]), set(info.get("words", []))
                score = (len(a & b) / len(a | b) if a | b else 0) + (0.15 if gap <= 24 else 0)
                if score > best_score:
                    best, best_score = vid, score
            video_of[pid] = best if best and best_score >= 0.3 else next_id()
        vid = video_of[pid]
        taken.add((vid, p["platform"]))
        info = videos.setdefault(vid, {"title": clean_title(p["title"]), "first_posted": p["posted"],
                                       "words": [], "format": None})
        if p["posted"] < info["first_posted"]:
            info["first_posted"] = p["posted"]
        info["words"] = sorted(set(info["words"]) | words(p["title"]))
        if ov.get("title"):
            info["title"] = ov["title"]
        info["format"] = ov.get("format") or p.get("format") or info.get("format") or guess_format(
            " ".join([p["title"], info["title"]]))
    return video_of, videos


def dashboard_rows(posts, state):
    snaps, rows = state.get("snaps", {}), []
    for p in posts:
        vid = state["video_of"][p["post_id"]]
        info = state["videos"][vid]
        s = snaps.get(p["post_id"], {})
        rows.append({
            "post_id": p["post_id"], "video_id": vid, "video": info["title"],
            "format": p.get("format") or info.get("format"), "category": None,
            "platform": p["platform"], "slot": None,
            "posted": sources.parse_time(p["posted"]).astimezone(sources.UK).date().isoformat(),
            "posted_at": p["posted"], "snapshot": p.get("numbers_from") or "live",
            "duration_s": p.get("duration_s"), "views": p.get("views"),
            "views_24h": s.get("24", {}).get("views"), "views_7d": s.get("168", {}).get("views"),
            **{k: p.get(k) for k in ("avg_watch_s", "full_watch_pct", "likes", "comments", "shares",
                                     "saves", "follows", "skip_rate", "url", "source")},
            "profile_visits": None, "link_clicks": None, "discord_joins": None,
        })
    return rows


# ------------------------------------------------------------------ snapshots
def record_snapshots(posts, state, now):
    snaps = state.setdefault("snaps", {})
    platform_of = state.setdefault("platform_of", {})
    new = []
    for p in posts:
        platform_of[p["post_id"]] = p["platform"]
        if p.get("views") is None:
            continue
        s = snaps.setdefault(p["post_id"], {})
        vals = {k: p.get(k) for k in METRICS if p.get(k) is not None}
        if p["source"] == "typed in":
            h = label_hours(p.get("numbers_from"))
            if h:
                if str(h) not in s:
                    new.append((p["post_id"], h))
                s[str(h)] = {**vals, "age_h": h}
            continue
        age = (now - sources.parse_time(p["posted"])).total_seconds() / 3600
        for m in MILESTONES:
            if str(m) not in s and m <= age <= m * 1.5 + 3:
                s[str(m)] = {**vals, "age_h": round(age, 1)}
                new.append((p["post_id"], m))
    return new


def usual(state, platform, hours, exclude, key="views"):
    vals = [s[str(hours)].get(key) for pid, s in state.get("snaps", {}).items()
            if pid != exclude and state["platform_of"].get(pid) == platform and str(hours) in s
            and s[str(hours)].get(key) is not None]
    return statistics.median(vals) if len(vals) >= 3 else None


# ------------------------------------------------------------------ main
def main():
    cfg = load(HERE / "config.json", {})
    state = load(DATA / "state.json", {})
    now = sources.parse_time(os.environ["BOT_NOW"]) if os.environ.get("BOT_NOW") else \
        dt.datetime.now(sources.UTC).replace(microsecond=0)
    now_uk = now.astimezone(sources.UK)
    webhook = os.environ.get("DISCORD_STATS_WEBHOOK", "").strip()
    if not webhook or os.environ.get("DRY_RUN") == "1":
        D.OUTBOX = []
    yt_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    ig_token = os.environ.get("INSTAGRAM_TOKEN", "").strip()
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    problems, notes, posts = [], [], []

    # ---- 1. collect
    yt_channel = (cfg.get("youtube") or {}).get("channel", "").strip()
    own_channel = None
    if yt_key and yt_channel and not yt_channel.startswith("@YOUR"):
        try:
            got, own_channel = sources.youtube_posts(yt_key, yt_channel,
                                                     cfg["youtube"].get("shorts_max_seconds", 180))
            posts += got
        except Exception as e:
            problems.append(f"YouTube didn't answer: {e}")
    elif not yt_key:
        problems.append("YouTube isn't connected yet: add the YOUTUBE_API_KEY secret (setup step 2).")
    else:
        problems.append("Put the PIRACY YouTube handle in config.json (setup step 2).")

    if ig_token:
        try:
            posts += sources.instagram_posts(ig_token, (cfg.get("instagram") or {}).get("api_version", "v24.0"))
        except Exception as e:
            problems.append(f"Instagram didn't answer: {e}")
        tok = state.setdefault("ig_token", {})
        h = hashlib.sha256(ig_token.encode()).hexdigest()[:12]
        if tok.get("hash") != h:
            tok.update({"hash": h, "added": sources.iso(now)})
        out_path = os.environ.get("IG_TOKEN_OUT")
        if out_path and (now - sources.parse_time(tok["added"])).days >= 7:
            try:
                r = sources.instagram_refresh(ig_token)
                pathlib.Path(out_path).write_text(r["access_token"])
                tok.update({"hash": hashlib.sha256(r["access_token"].encode()).hexdigest()[:12],
                            "added": sources.iso(now)})
            except Exception as e:
                problems.append(f"Couldn't renew the Instagram token: {e}")
        elif not out_path and (now - sources.parse_time(tok["added"])).days >= 50:
            runs_out = (sources.parse_time(tok["added"]) + dt.timedelta(days=60)).astimezone(sources.UK)
            notes.append(f"**Instagram token runs out around {runs_out:%a %d %b}.** Make a new one "
                         "(setup step 4), or add GH_SECRETS_PAT so the bot renews it itself.")

    manual, bad_rows = sources.manual_posts(HERE / "manual" / "posts.csv")
    posts += manual
    problems += bad_rows

    members = None
    invite = (cfg.get("discord") or {}).get("invite_code", "").strip()
    if invite:
        try:
            members, _ = sources.discord_members(invite)
        except Exception as e:
            problems.append(f"Couldn't read the Discord member count: {e}")
    guild = (cfg.get("discord") or {}).get("guild_id", "").strip()
    if bot_token and guild:
        try:
            uses = sources.discord_invite_uses(bot_token, guild)
            hist = state.setdefault("invite_uses", {})
            hist[now_uk.date().isoformat()] = uses
            for d in sorted(hist)[:-60]:
                del hist[d]
            week_ago = (now_uk.date() - dt.timedelta(days=7)).isoformat()
            base = next((hist[d] for d in sorted(hist) if d >= week_ago), None)
            if base:
                names = cfg["discord"].get("invite_names", {})
                joins = {names.get(c, c): u - base.get(c, 0) for c, u in uses.items() if u - base.get(c, 0) > 0}
                if joins:
                    notes.append("**Discord joins this week:** " + " · ".join(
                        f"{k} {v:.0f}" for k, v in sorted(joins.items(), key=lambda kv: -kv[1])))
        except Exception as e:
            problems.append(f"Couldn't read Discord invites (does the bot have Manage Server?): {e}")

    # ---- 2. group clips and take snapshots
    links = sources.overrides(HERE / "manual" / "links.csv")
    assign_videos(posts, state, links)
    new_snaps = record_snapshots(posts, state, now)
    rows = dashboard_rows(posts, state)
    by_pid = {p["post_id"]: p for p in posts}
    videos = {v: i for v, i in state["videos"].items() if any(r["video_id"] == v for r in rows)}

    first_run = not state.get("started")
    seen = set(state.get("seen", []))
    messages = []      # lists of embeds, in order

    if first_run:
        report, weekly_state = discord_report.build(rows, None, cfg.get("dashboard_url") or None,
                                                    now_uk.date().isoformat())
        messages.append(D.notice("Stats bot is live", (
            "From now on this channel gets new-video alerts, 24-hour and 7-day check-ins, a heads-up when "
            "a clip takes off, a scoreboard that updates every few hours, and a report every Monday. "
            "**Pin the scoreboard message below** so it's easy to find."), now))
        messages += D.pack(report)
        state["weekly_prev"] = weekly_state
    else:
        # ---- 3a. new videos
        fresh = [p for p in posts if p["post_id"] not in seen]
        for vid in sorted({state["video_of"][p["post_id"]] for p in fresh}):
            ps = [p for p in fresh if state["video_of"][p["post_id"]] == vid]
            messages.append(D.new_video(vid, state["videos"][vid], ps, now))
        # ---- 3b. check-ins and take-offs
        checkins = {}
        alert_cfg = cfg.get("alerts", {})
        took_off = set(state.get("took_off", []))
        for pid, hours in new_snaps:
            p = by_pid[pid]
            vid = state["video_of"][pid]
            snap = state["snaps"][pid][str(hours)]
            if hours in (24, 168):
                checkins.setdefault((vid, hours), []).append(
                    (p["platform"], snap, usual(state, p["platform"], hours, pid), None))
            base = usual(state, p["platform"], hours, pid)
            if hours <= 48 and base and pid not in took_off and snap.get("views"):
                ratio = snap["views"] / base
                if ratio >= alert_cfg.get("take_off_multiplier", 2.0) and \
                        snap["views"] >= alert_cfg.get("take_off_min_views", 200):
                    messages.append(D.taking_off(vid, state["videos"][vid], p, hours, ratio, now))
                    took_off.add(pid)
        state["took_off"] = sorted(took_off)
        for (vid, hours), per in sorted(checkins.items()):
            order = [n for n, _ in discord_report.PLATFORMS]
            per.sort(key=lambda x: order.index(x[0]))
            messages.append(D.check_in(vid, state["videos"][vid], hours, per, now))

    # ---- 4. weekly report (and the daily scan of other dev Shorts)
    scan_cfg = cfg.get("scanner", {})
    store = state.setdefault("scanner", {})
    if yt_key and scan_cfg.get("enabled", True) and state.get("scan_day") != now_uk.date().isoformat():
        try:
            scanner.run(yt_key, scan_cfg.get("queries", ["roblox devlog"]), scan_cfg.get("days", 7),
                        set(scan_cfg.get("exclude_channels", [])) | ({own_channel} if own_channel else set()),
                        store, now)
            state["scan_day"] = now_uk.date().isoformat()
        except Exception as e:
            problems.append(f"The Roblox dev Shorts scan failed: {e}")
    scan = scanner.summary(store, now)
    recs = recommend.advice(rows, state.get("snaps", {}), scan, now)

    wk = cfg.get("weekly", {})
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    week_key = f"{now_uk.isocalendar()[0]}-W{now_uk.isocalendar()[1]:02d}"
    due = (not first_run and days[now_uk.weekday()] == wk.get("weekday", "Mon") and now_uk.hour >= wk.get("hour_uk", 18)
           and state.get("weekly_done") != week_key)
    if due or os.environ.get("FORCE_WEEKLY") == "1":
        report, weekly_state = discord_report.build(rows, None if first_run else state.get("weekly_prev"),
                                                    cfg.get("dashboard_url") or None, now_uk.date().isoformat())
        report.append(D.recommendations_embed(recs[:5]))
        report.append(scanner.embed(scan))
        messages += D.pack(report)
        state["weekly_prev"] = weekly_state
        state["weekly_done"] = week_key

    # ---- 5. reminders for hand-typed numbers
    for p in manual:
        if p.get("views") is None:
            continue
        age_d = (now - sources.parse_time(p["posted"])).total_seconds() / 86400
        h = label_hours(p.get("numbers_from"))
        vid = state["video_of"][p["post_id"]]
        if age_d >= 7 and (h or 0) < 168:
            notes.append(f"**{vid} on {p['platform']}** is a week old: add its 7-day numbers to manual/posts.csv.")
        elif age_d >= 1 and (h or 0) < 24:
            notes.append(f"**{vid} on {p['platform']}**: add its 24-hour numbers to manual/posts.csv.")

    # ---- 6. scoreboard
    board_notes = problems[:3] + notes[:3] + ([f"**Tip:** {recs[0]}"] if recs else [])
    last = state.get("last_views") or {}
    board = D.scoreboard(rows, videos, last if not first_run else {}, members, board_notes, now,
                         cfg.get("dashboard_url") or None, cfg.get("run_every_hours", 3))

    # ---- send everything, then remember it
    for m in messages:
        D.send(webhook, m)
    board_id = state.get("board_id")
    if not (board_id and D.edit(webhook, board_id, board)):
        state["board_id"] = D.send(webhook, board)

    state["started"] = state.get("started") or sources.iso(now)
    state["seen"] = sorted(seen | {p["post_id"] for p in posts})
    state["last_views"] = {r["post_id"]: r["views"] for r in rows if r["views"] is not None}
    if members is not None:
        state["last_views"]["_members"] = members
    state["last_run"] = sources.iso(now)
    save(DATA / "state.json", state)
    save(DATA / "posts.json", {"rows": rows, "meta": [
        {"label": "Made by", "value": "PIRACY stats bot (bot.py)"},
        {"label": "Updated", "value": sources.iso(now)}]})
    if D.OUTBOX is not None:
        D.dump_outbox(DATA / "outbox.json")
    print(f"{now_uk:%Y-%m-%d %H:%M} UK: {len(posts)} posts, {len(videos)} videos, "
          f"{len(messages)} message(s) sent, scoreboard {'edited' if board_id else 'posted'}.")
    for p in problems:
        print("  problem:", p)


def report_crash():
    """Tell the Discord channel the run failed, with any secrets blanked out."""
    text = traceback.format_exc()
    for key in ("DISCORD_STATS_WEBHOOK", "YOUTUBE_API_KEY", "INSTAGRAM_TOKEN", "DISCORD_BOT_TOKEN", "GH_SECRETS_PAT"):
        if os.environ.get(key):
            text = text.replace(os.environ[key], "[hidden]")
    last = [line for line in text.strip().splitlines() if line.strip()][-1][:300]
    webhook = os.environ.get("DISCORD_STATS_WEBHOOK", "").strip()
    if webhook and os.environ.get("DRY_RUN") != "1":
        try:
            sources.http("POST", webhook, body={"username": D.BOT_NAME, "allowed_mentions": {"parse": []}, "embeds": [{
                "color": 0xDD2E44, "title": "The stats bot hit a problem",
                "description": f"`{last}`\nThe full error is in GitHub → Actions → the failed run → run → Run the bot."}]})
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        report_crash()
        sys.exit(1)
