#!/usr/bin/env python3
"""PIRACY social stats, V2. Runs every hour on GitHub Actions.

Each run:
  1. collects numbers from YouTube (+ YouTube Analytics), TikTok, Instagram and Discord,
     plus anything typed into manual/posts.csv for apps that aren't connected;
  2. adds them to the history (never overwriting good numbers with blanks);
  3. works out gains, growth curves, "your usual", milestones and insights;
  4. scans what's working for other Roblox devs (daily) and reads the trend bot's board;
  5. updates Discord: the live scoreboard, alerts, check-ins, the Monday report, per-app tabs;
  6. builds the website (stats/_site), which the workflow publishes to GitHub Pages.

Secrets (GitHub → Settings → Secrets → Actions), all optional except the first two:
  DISCORD_STATS_WEBHOOK, YOUTUBE_API_KEY, DISCORD_TABS_WEBHOOK,
  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, INSTAGRAM_TOKEN
DRY_RUN=1 sends nothing to Discord (messages go to data/outbox.json).
"""
import datetime as dt
import json
import os
import pathlib
import sys
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from piracy import analysis, charts, collect, discord_v2 as D, research, site, store as S, util, vault as V  # noqa: E402

ROOT = HERE.parent
DATA = pathlib.Path(os.environ.get("STATS_DATA") or HERE / "data")
SITE_OUT = pathlib.Path(os.environ.get("STATS_SITE") or HERE / "_site")
CONFIG = pathlib.Path(os.environ.get("STATS_CONFIG") or HERE / "config.json")


def env(name):
    return (os.environ.get(name) or "").strip()


def load_overrides(path):
    import csv
    out = {}
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items() if k}
                if r.get("post") and not r["post"].startswith("#"):
                    out[r["post"]] = r
    except FileNotFoundError:
        pass
    return out


def import_v1_groups(store):
    """Keep the video ids (V00, V01...) the first bot gave out."""
    if store.state.get("groups"):
        return
    v1 = util.load_json(ROOT / "piracy-bot" / "data" / "state.json", {})
    groups = {}
    for vid, info in (v1.get("videos") or {}).items():
        groups[vid] = {"title": info.get("title"), "first_posted": info.get("first_posted"),
                       "words": info.get("words", []), "format": info.get("format")}
    if groups:
        store.state["groups"] = groups
        store.state["video_of"] = {pid: vid for pid, vid in (v1.get("video_of") or {}).items()}


def main():
    t0 = time.time()
    now = util.now_utc()
    cfg = util.load_json(CONFIG, {})
    st = S.Store(DATA)
    vault = V.Vault(DATA / "vault.json")
    state = st.state
    dry = env("DRY_RUN") == "1"
    site_url = (cfg.get("site") or {}).get("url") if (cfg.get("site") or {}).get("ready") else None
    print(f"PIRACY stats V2 · {util.uk(now):%a %d %b %H:%M} UK · {'DRY RUN' if dry else 'live' if cfg.get('discord', {}).get('live') else 'shadow mode'}")

    # ---------------------------------------------------------------- 1. collect
    yt_cfg = cfg.get("youtube") or {}
    results = {}
    results["youtube"] = collect.youtube(env("YOUTUBE_API_KEY"), yt_cfg.get("channel", ""),
                                         yt_cfg.get("shorts_max_seconds", 180))
    if results["youtube"].status == "ok":
        ids = [p["id"][3:] for p in results["youtube"].posts]
        ya = collect.youtube_analytics(vault, env("GOOGLE_CLIENT_ID"), env("GOOGLE_CLIENT_SECRET"), ids,
                                       util.uk(now).date().isoformat())
        results["youtube_analytics"] = ya
        if ya.status == "ok":
            for p in results["youtube"].posts:
                for k, v in (ya.extra["per_video"].get(p["id"]) or {}).items():
                    if v is not None:
                        p[k] = v
    results["tiktok"] = collect.tiktok(vault, env("TIKTOK_CLIENT_KEY"), env("TIKTOK_CLIENT_SECRET"), now)
    results["instagram"] = collect.instagram(vault, env("INSTAGRAM_TOKEN"), now,
                                             (cfg.get("instagram") or {}).get("api_version", "v24.0"))
    results["discord"] = collect.discord((cfg.get("discord") or {}).get("invite_code", ""))
    manual_posts, manual_problems = collect.manual(HERE / "manual" / "posts.csv")
    connected = {pl for pl in util.PLATFORMS if results[pl].status == "ok"}
    manual_posts = [p for p in manual_posts if p["platform"] not in connected]
    for pid, p in st.posts.items():           # typed rows give way once the app is connected
        if p.get("source") == "typed" and p.get("platform") in connected and p.get("status") == "live":
            p["status"] = "superseded"
    manual_res = collect.Result("manual", "ok", "typed in", manual_posts)

    # ---------------------------------------------------------------- 2. history
    fresh = st.merge([results[pl] for pl in util.PLATFORMS] + [manual_res], now)
    ts = util.iso(now)
    for pl in util.PLATFORMS:
        r = results[pl]
        if r.status != "ok":
            continue
        live = st.live(pl)
        st.record_account(ts, pl, {"followers": r.account.get("followers"),
                                   "total_views": sum((p.get("metrics") or {}).get("views") or 0 for p in live.values()),
                                   "posts": len(live), "likes_total": r.account.get("likes_total"),
                                   "channel_views": r.account.get("channel_views")})
    if results["discord"].status == "ok":
        st.record_account(ts, "discord", {"followers": results["discord"].account.get("followers")})

    # statuses, and a running count of failures for health alerts
    statuses, health_msgs = {}, []
    health = state.setdefault("health", {})
    typed_platforms = {p["platform"] for p in manual_posts}
    for pl in util.PLATFORMS + ["discord", "youtube_analytics"]:
        r = results.get(pl)
        if r is None:
            continue
        s = r.status
        if s == "not_connected" and pl in typed_platforms:
            s = "typed"
        if s == "error" and pl in util.PLATFORMS and st.live(pl):
            s = "stale"
        h = health.setdefault(pl, {"fails": 0})
        if r.status == "error":
            h["fails"] = h.get("fails", 0) + 1
            h["message"] = r.message
            if h["fails"] == 3 and not h.get("alerted"):
                health_msgs.append((pl, r.message, False))
                h["alerted"] = True
        else:
            if h.get("alerted") and r.status == "ok":
                health_msgs.append((pl, "", True))
            h.update({"fails": 0, "alerted": False})
            if r.status == "ok":
                h["last_ok"] = ts
        statuses[pl] = {"status": s, "message": r.message, "last_ok": h.get("last_ok"),
                        "account": {k: v for k, v in r.account.items() if k in ("name", "followers", "avatar", "handle",
                                                                                 "token_expires", "online")},
                        "fails": h.get("fails", 0)}
    for pl in ("tiktok", "google", "instagram"):
        meta = vault.meta(pl)
        if meta:
            key = "youtube_analytics" if pl == "google" else pl
            statuses.setdefault(key, {})["vault"] = meta
    if manual_problems:
        statuses["manual"] = {"status": "error", "message": "; ".join(manual_problems)[:400]}

    # ---------------------------------------------------------------- 3. analysis
    import_v1_groups(st)
    video_of, groups = S.group_videos(st, load_overrides(HERE / "manual" / "links.csv"))
    summary = analysis.build(st, now, statuses)
    rows = analysis.post_rows(st, now, summary, video_of, groups)
    stones = analysis.milestones(st, now, summary)
    prog = analysis.progress(summary)
    notes = analysis.insights(st, now, summary, video_of, groups)

    # ---------------------------------------------------------------- 4. research
    scan_cfg = cfg.get("scanner") or {}
    scan_store = util.load_json(DATA / "research.json", {})
    if env("YOUTUBE_API_KEY") and scan_cfg.get("enabled", True) and state.get("scan_day") != util.uk_day(now):
        try:
            n = research.scan(env("YOUTUBE_API_KEY"), scan_cfg, scan_store, now)
            state["scan_day"] = util.uk_day(now)
            print(f"  scan: {n} Shorts found")
        except Exception as e:
            statuses["research"] = {"status": "error", "message": f"The creator scan failed: {e}"}
    util.save_json(DATA / "research.json", scan_store)
    scan = research.patterns(scan_store, now, scan_cfg.get("days", 7))
    trends = state.get("trends_cache") or {}
    tb = cfg.get("trendbot") or {}
    if tb.get("board_url") and util.hours_between(trends.get("fetched", "1970-01-01T00:00:00Z"), now) >= 3:
        try:
            trends = research.trendbot(tb["board_url"], tb.get("site"))
            trends["fetched"] = ts
            state["trends_cache"] = trends
        except Exception as e:
            statuses["trends"] = {"status": "error", "message": f"Couldn't read the trend bot's board: {e}"}
    exps = research.experiments(summary, scan, rows)

    # ---------------------------------------------------------------- 5. Discord
    dcfg = cfg.get("discord") or {}
    live_mode = bool(dcfg.get("live")) and not dry
    outbox = []
    disc = D.Discord(env("DISCORD_STATS_WEBHOOK"), live_mode, outbox)
    tabs_hook = D.Discord(env("DISCORD_TABS_WEBHOOK"), live_mode, outbox)
    sent = state.setdefault("sent", {})
    first_run = not state.get("v2_started")
    acc_latest = {pl: (st.accounts().get(pl) or [[None, {}]])[-1][1] for pl in util.PLATFORMS}

    def once(key, build):
        if key in sent:
            return
        sent[key] = ts
        st.save()                       # remember before sending: a crash can't cause a repeat
        if first_run:
            return
        try:
            msg = build()
            if msg:
                disc.send(msg, kind=key.split(":")[0])
        except Exception as e:
            print(f"  couldn't send {key}: {e}")

    curves = summary["curves"]
    for pid in sorted(st.posts, key=lambda k: st.posts[k].get("posted") or ""):
        p = st.posts[pid]
        if p.get("status") != "live" or not p.get("posted"):
            continue
        age = util.hours_between(p["posted"], now)
        base = analysis.usual(curves, p["platform"], exclude=pid, posts=st.posts)
        vid = video_of.get(pid)
        if age <= 48:
            once(f"new:{pid}", lambda p=p, vid=vid, base=base: D.new_post(
                {**p, "id": pid}, f"{vid} · {groups.get(vid, {}).get('format') or 'clip'}" if vid else None, base, site_url))
        else:
            sent.setdefault(f"new:{pid}", ts)
        c = curves.get(pid, {})
        for h in (24, 168):
            if age >= h and h in c and age <= h + 48:
                once(f"checkin:{pid}:{h}", lambda p=p, h=h, c=c, base=base: D.check_in({**p, "id": pid}, h, c[h], base, site_url))
            elif age > h + 48:
                sent.setdefault(f"checkin:{pid}:{h}", ts)
        vs = analysis.versus_usual(c, base)
        a = cfg.get("alerts") or {}
        if vs and age <= 48 and vs[1] >= a.get("take_off_multiplier", 2.0) and \
                (p.get("metrics") or {}).get("views", 0) >= a.get("take_off_min_views", 200):
            once(f"takeoff:{pid}", lambda p=p, vs=vs, base=base: D.take_off(
                {**p, "id": pid}, vs[0], vs[1], vs[2], base[vs[0]]["median"], site_url))
    prog_by = {(x["platform"], x["kind"]): x for x in prog}
    for m in stones:
        fresh_enough = util.hours_between(m["ts"], now) <= 48 and not m.get("before")
        if not fresh_enough:
            sent.setdefault(f"milestone:{m['key']}", ts)
            continue
        if m["key"].startswith("video:"):
            v = (st.posts.get(m["post"], {}).get("metrics") or {}).get("views")
            nx = analysis.next_step(v, analysis.VIDEO_STEPS)
            pv = analysis.prev_step(v, analysis.VIDEO_STEPS)
            nxt = {"next": nx, "pct": (v - pv) / (nx - pv)} if v and nx else None
        elif m["key"].startswith("views:"):
            nxt = prog_by.get((m["platform"], "views"))
        else:
            nxt = prog_by.get((m["platform"], "members" if m["platform"] == "discord" else "followers"))
        once(f"milestone:{m['key']}", lambda m=m, nxt=nxt: D.milestone(m, nxt, site_url))
    for pl, msg, fixed in health_msgs:
        if not first_run:
            try:
                disc.send(D.health(pl, msg, fixed), kind="health")
            except Exception as e:
                print(f"  couldn't send the health note: {e}")

    # top posts this week (by views gained in 7 days, else total)
    def week_gain(r):
        hist = [(util.parse(t), v) for t, v in r["history"]]
        if not hist:
            return None
        cut = now - dt.timedelta(days=7)
        before = [v for t, v in hist if t <= cut]
        start = before[-1] if before else (0 if util.parse(r["posted"]) >= cut else None)
        return None if start is None else (r["metrics"].get("views") or 0) - start
    live_rows = [r for r in rows if r["status"] == "live" and r["metrics"].get("views") is not None]
    for r in live_rows:
        r["gain_7d"] = week_gain(r)
    top = sorted(live_rows, key=lambda r: (r["gain_7d"] if r["gain_7d"] is not None else -1, r["metrics"]["views"]),
                 reverse=True)[:3]
    top_ctx = [{"title": r["title"], "url": r["url"], "platform": r["platform"], "views": r["metrics"]["views"],
                "gain": r["gain_7d"]} for r in top]
    board_notes = [n["text"] for n in notes if n["tag"] in ("OBSERVED", "WATCH") and n["kind"] != "gain"][:2]
    def goal(x):
        what = {"views": f"total views on {util.SHORT[x['platform']]}", "followers":
                f"{'subscribers' if x['platform'] == 'youtube' else 'followers'} on {util.SHORT[x['platform']]}",
                "members": "Discord members"}[x["kind"]]
        return f"**{util.fmt_int(x['next'])} {what}** ({x['pct'] * 100:.0f}% there)"
    next_line = ("🗺️ Next treasure: " + " · ".join(goal(x) for x in prog[:2])) if prog else None
    disp_status = {pl: statuses[pl]["status"] for pl in util.PLATFORMS}
    yt_avatar = (results["youtube"].account or {}).get("avatar") or (statuses.get("youtube", {}).get("account") or {}).get("avatar")
    board_png = None
    try:
        panels = []
        for pl in util.PLATFORMS:
            if not summary["platforms"][pl]["posts"]:
                continue
            pp = analysis.platform_points(st, pl)
            start = now - dt.timedelta(days=7, hours=3)
            panels.append({"platform": pl, "status": disp_status[pl],
                           "series": analysis.total_series(pp, st.posts, now, start, step_h=1),
                           "uploads": [(p["posted"], p.get("title")) for p in st.live(pl).values()],
                           "gain_24h": summary["platforms"][pl]["gain_24h"],
                           "total": summary["platforms"][pl]["total_views"]})
        if panels:
            board_png = charts.scoreboard(panels, now)
    except Exception as e:
        print(f"  chart failed: {e}")
    board = D.scoreboard({"summary": summary, "statuses": disp_status, "accounts": acc_latest, "top": top_ctx,
                          "notes": board_notes, "now": now, "site": site_url, "avatar": yt_avatar,
                          "chart": "board.png" if board_png else None, "next": next_line})
    files = [("board.png", board_png)] if board_png else None
    if live_mode and not state.get("board_id"):
        v1 = util.load_json(ROOT / "piracy-bot" / "data" / "state.json", {})
        if str(v1.get("board_id") or "").isdigit() and dcfg.get("takeover_v1", True):
            state["board_id"] = v1["board_id"]
            state["v1_board"] = v1["board_id"]
            state.setdefault("tabs", {k: v for k, v in (v1.get("tabs") or {}).items()})
    board_id = state.get("board_id") if live_mode else state.get("shadow_board")
    # one-off: post a fresh scoreboard at the bottom of the channel (with a short note on
    # what's new) and remove the old one, whenever config "repost_board" gets a new value
    repost = dcfg.get("repost_board")
    just_posted = False
    if live_mode and repost and state.get("reposted") != repost:
        try:
            if f"launch:{repost}" not in sent:
                sent[f"launch:{repost}"] = ts
                st.save()
                disc.send(D.launch(site_url), kind="launch")
            msg = disc.send(board, files, kind="scoreboard")
            if (msg or {}).get("id"):
                if str(board_id or "").isdigit():
                    disc.delete(board_id)
                state["board_id"] = msg["id"]
                state["reposted"] = repost
                just_posted = True
                st.save()
                print("  posted a fresh scoreboard at the bottom of the channel: pin it")
        except Exception as e:
            print(f"  couldn't post the fresh scoreboard: {e}")
    try:
        if just_posted:
            pass
        elif not (board_id and disc.edit(board_id, board, files, kind="scoreboard")):
            msg = disc.send(board, files, kind="scoreboard")
            new_id = (msg or {}).get("id")
            if live_mode:
                if state.get("v1_board") and state["v1_board"] == board_id:
                    disc.delete(board_id)
                state["board_id"] = new_id
                print("  posted a new scoreboard: pin it in Discord")
            else:
                state["shadow_board"] = new_id
    except Exception as e:
        statuses["discord_post"] = {"status": "error", "message": f"Couldn't update the scoreboard: {e}"}
        print(f"  scoreboard failed: {e}")

    # weekly report: Mondays after 18:00 UK
    wk = cfg.get("weekly") or {}
    uk_now = util.uk(now)
    week_key = f"{uk_now.isocalendar()[0]}-W{uk_now.isocalendar()[1]:02d}"
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekly_due = (days[uk_now.weekday()] == wk.get("weekday", "Mon") and uk_now.hour >= wk.get("hour_uk", 18)
                  and state.get("weekly_done") != week_key) or env("FORCE_WEEKLY") == "1"
    if weekly_due and not first_run:
        try:
            png = charts.weekly({pl: summary["platforms"][pl]["daily"] for pl in util.PLATFORMS
                                 if summary["platforms"][pl]["daily"]}, now)
            msg = D.weekly({"summary": summary, "now": now, "chart": "week.png", "top": top_ctx,
                            "experiments": exps, "scan": scan, "trends": trends, "site": site_url})
            disc.send(msg, [("week.png", png)], kind="weekly")
            state["weekly_done"] = week_key
        except Exception as e:
            print(f"  weekly report failed: {e}")
    elif first_run and weekly_due:
        state["weekly_done"] = week_key

    # per-app tabs (forum posts), if that webhook is set
    if env("DISCORD_TABS_WEBHOOK"):
        tabs = state.setdefault("tabs", {})
        names = {"youtube": "YouTube Shorts", "tiktok": "TikTok", "instagram": "Instagram Reels"}
        for pl, v1name in names.items():
            try:
                msg = D.platform_tab(pl, rows, summary, disp_status[pl], acc_latest.get(pl), now, site_url)
                t = tabs.get(v1name) or {}
                if live_mode:
                    if not tabs_hook.edit(t.get("message"), msg, thread_id=t.get("thread"), kind="tab"):
                        r = tabs_hook.send(msg, thread_name=f"{D.ICON[pl]} {v1name}", kind="tab")
                        tabs[v1name] = {"message": r.get("id"), "thread": r.get("channel_id")}
                else:
                    tabs_hook.send(msg, kind="tab")
            except Exception as e:
                print(f"  tab {pl} failed: {e}")

    # ---------------------------------------------------------------- 6. website
    connect = {"tiktok_client_key": env("TIKTOK_CLIENT_KEY") or None,
               "google_client_id": env("GOOGLE_CLIENT_ID") or None,
               "redirect": ((cfg.get("site") or {}).get("url") or "").rstrip("/") + "/connect.html",
               "repo": cfg.get("repo_url"), "instagram": bool(env("INSTAGRAM_TOKEN"))}
    research_out = {"scan": scan, "experiments": exps, "guide": research.FIELD_GUIDE, "trends": trends}
    run_every = (cfg.get("site") or {}).get("run_every_hours", 1)
    try:
        site.build(SITE_OUT, HERE / "site", st, now, summary, rows, groups, stones, prog, notes,
                   research_out, statuses, cfg, connect, run_every)
    except Exception as e:
        print(f"  website build failed: {e}")
        traceback.print_exc()

    # ---------------------------------------------------------------- 7. remember
    state["v2_started"] = state.get("v2_started") or ts
    state["last_run"] = ts
    st.runs.append({"ts": ts, "ok": all(statuses[pl]["status"] in ("ok", "not_connected", "typed")
                                        for pl in util.PLATFORMS),
                    "statuses": {k: v.get("status") for k, v in statuses.items()},
                    "seconds": round(time.time() - t0, 1), "sent": disc.sent + tabs_hook.sent,
                    "mode": "dry" if dry else "live" if live_mode else "shadow"})
    vault.save()
    st.save()
    if outbox:
        util.save_json(DATA / "outbox.json", outbox[-60:])
    for k, v in results.items():
        print(f"  {k:18} {v.status:14} {v.message}")
    print(f"  {len(fresh)} new post(s), {len(rows)} tracked, {disc.sent + tabs_hook.sent} Discord call(s), "
          f"{len(outbox)} in the outbox, {time.time() - t0:.1f}s")


def report_crash():
    text = "".join(traceback.format_exc()).strip().splitlines()
    from piracy import net
    last = net.scrub([line for line in text if line.strip()][-1])[:300]
    print("\n".join(net.scrub(t) for t in text))
    cfg = util.load_json(CONFIG, {})
    hook = env("DISCORD_STATS_WEBHOOK")
    if hook and (cfg.get("discord") or {}).get("live") and env("DRY_RUN") != "1":
        try:
            D.Discord(hook, True).send([D.card([D.text(
                f"### 🛠️ The stats bot hit a problem\n`{last}`\n-# The numbers on the scoreboard are the last good ones. "
                "Full details: GitHub → Actions → the failed run.")], D.ACCENT["bad"])], kind="crash")
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        report_crash()
        sys.exit(1)
