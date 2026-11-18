"""Turning the history into answers: gains over time, growth curves, "your usual",
milestones and plain-English insights.

Rules this module keeps:
- apps are never added together (they count views differently);
- a missing number stays missing, it is never treated as zero;
- comparisons wait for enough posts, and say how many they are based on;
- patterns are described as patterns, never as proven causes.
"""
import datetime as dt
import statistics

from . import util

CHECKPOINTS = [1, 3, 6, 12, 24, 48, 72, 168, 720]
MIN_USUAL = 3        # posts needed before "your usual" is shown
MIN_BAND = 5         # posts needed before the usual range (middle half) is shown
MIN_FORMAT = 5       # posts per format before formats are compared
VIEW_STEPS = [100, 250, 500, 1000, 2500, 5000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000,
              1_000_000, 2_500_000, 5_000_000, 10_000_000]
FOLLOW_STEPS = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10_000, 25_000, 50_000, 100_000, 250_000, 1_000_000]
VIDEO_STEPS = [1000, 5000, 10_000, 50_000, 100_000, 500_000, 1_000_000, 5_000_000]


# ------------------------------------------------------------------ one post over time
def points(store, pid):
    """[(datetime, views)] starting at (posted, 0)."""
    p = store.posts.get(pid, {})
    out = []
    if p.get("posted"):
        out.append((util.parse(p["posted"]), 0.0))
    for ts, vals in store.history().get(pid, []):
        if vals.get("views") is not None:
            out.append((util.parse(ts), vals["views"]))
    out.sort(key=lambda x: x[0])
    return out


def value_at(pts, t, tracked_until=None):
    """Views at time t: linear between the two readings around it, if they're close enough."""
    if not pts or t < pts[0][0]:
        return 0.0 if pts and t < pts[0][0] else None
    before = [x for x in pts if x[0] <= t]
    after = [x for x in pts if x[0] >= t]
    a = before[-1]
    if a[0] == t:
        return a[1]
    if not after:
        # after the last reading: unchanged since (readings are written whenever numbers move)
        if tracked_until and t <= tracked_until:
            return a[1]
        return None
    b = after[0]
    span = (b[0] - a[0]).total_seconds() / 3600
    age = (t - pts[0][0]).total_seconds() / 3600
    if span > max(3.0, 0.6 * age):
        return None
    if a is pts[0] and (b[0] - pts[0][0]).total_seconds() / 3600 > 1.25 * age:
        return None          # only the posting moment before it: too far to guess
    f = (t - a[0]).total_seconds() / max((b[0] - a[0]).total_seconds(), 1)
    return a[1] + f * (b[1] - a[1])


def step_at(pts, t):
    """Views at t as last recorded (for totals). None when nothing was recorded by then."""
    if not pts:
        return None
    if t < pts[0][0]:
        return 0.0
    v = None
    for x in pts:
        if x[0] <= t:
            v = x[1]
        else:
            break
    return v


def curve(store, pid, now):
    p = store.posts[pid]
    pts = points(store, pid)
    tracked = util.parse(p.get("last_seen") or util.iso(now))
    if p.get("source") == "typed":
        tracked = pts[-1][0] if pts else tracked
    out = {}
    for h in CHECKPOINTS:
        t = util.parse(p["posted"]) + dt.timedelta(hours=h)
        if t > now:
            break
        v = value_at(pts, t, tracked)
        if v is not None:
            out[h] = round(v)
    return out


# ------------------------------------------------------------------ "your usual"
def usual(curves, platform, exclude=None, posts=None):
    """{hours: {median, lo, hi, n}} from other live posts on the same app."""
    out = {}
    for h in CHECKPOINTS:
        vals = [c[h] for pid, c in curves.items()
                if pid != exclude and h in c and (posts or {}).get(pid, {}).get("platform") == platform]
        if len(vals) >= MIN_USUAL:
            vals.sort()
            entry = {"median": statistics.median(vals), "n": len(vals)}
            if len(vals) >= MIN_BAND:
                q = statistics.quantiles(vals, n=4)
                entry["lo"], entry["hi"] = q[0], q[2]
            out[h] = entry
    return out


def versus_usual(c, base):
    """The latest checkpoint where both exist: (hours, ratio, n)."""
    for h in sorted(c, reverse=True):
        if h in base and base[h]["median"]:
            return h, c[h] / base[h]["median"], base[h]["n"]
    return None


# ------------------------------------------------------------------ app totals over time
def platform_points(store, platform):
    return {pid: points(store, pid) for pid in store.live(platform)}


def total_at(pp, posts, t):
    """Sum of live posts' views at t; (value, complete?). A post that was already up at t
    but had no reading yet makes the total incomplete (its views then are unknown)."""
    total, complete = 0.0, True
    for pid, pts in pp.items():
        posted = util.parse(posts[pid]["posted"]) if posts[pid].get("posted") else None
        if posted and t < posted:
            continue
        readings = pts[1:] if posted else pts             # skip the synthetic zero
        if not readings or t < readings[0][0]:
            gap = (readings[0][0] - posted).total_seconds() if posted and readings else None
            if gap is not None and gap <= 6 * 3600:
                # first reading came within a few hours of posting: estimate the climb from zero
                total += readings[0][1] * (t - posted).total_seconds() / max(gap, 1)
                continue
            complete = False
            continue
        total += step_at(readings, t)
    return total, complete


def gain(pp, posts, start, end):
    a, ca = total_at(pp, posts, start)
    b, cb = total_at(pp, posts, end)
    if not ca:
        return None
    return b - a


def daily(pp, posts, now, days=30):
    """[(UK date, views gained that day or None)] oldest first, from when tracking began."""
    today = util.uk(now).date()
    first = min((pts[1][0] for pts in pp.values() if len(pts) > 1), default=None)
    out = []
    for i in range(days - 1, -1, -1):
        d = today - dt.timedelta(days=i)
        start = dt.datetime.combine(d, dt.time(0), util.UK).astimezone(util.UTC)
        end = min(start + dt.timedelta(days=1), now)
        if first is None or end <= first:
            continue
        g = gain(pp, posts, start, end)
        out.append((d.isoformat(), round(g) if g is not None else None))
    return out


def total_series(pp, posts, now, start, step_h=3):
    """Total views every few hours from start to now (for charts)."""
    out, t = [], start
    while t <= now:
        v, complete = total_at(pp, posts, t)
        out.append((util.iso(t), round(v) if complete else None))
        t += dt.timedelta(hours=step_h)
    v, complete = total_at(pp, posts, now)
    out.append((util.iso(now), round(v) if complete else None))
    return out


# ------------------------------------------------------------------ engagement
ENGAGE_KEYS = {"youtube": ["likes", "comments", "shares"], "tiktok": ["likes", "comments", "shares"],
               "instagram": ["likes", "comments", "shares", "saves"]}


def engagement(posts):
    views = inter = 0.0
    for p in posts:
        m = p.get("metrics", {})
        if not m.get("views"):
            continue
        views += m["views"]
        inter += sum(m.get(k) or 0 for k in ENGAGE_KEYS.get(p["platform"], ["likes", "comments"]))
    return inter / views if views else None


# ------------------------------------------------------------------ milestones
def next_step(value, steps):
    for s in steps:
        if value is None or s > value:
            return s
    return None


def prev_step(value, steps):
    best = 0
    for s in steps:
        if value is not None and s <= value:
            best = s
    return best


def crossings(series, steps):
    """[(step, ts, before_tracking)] for each step reached, with when it first was.
    Steps already passed at the first reading collapse to the highest one, flagged."""
    out, done, first = [], set(), True
    for ts, v in series:
        if v is None:
            continue
        hit = [s for s in steps if s not in done and v >= s]
        done.update(hit)
        if first and hit:
            out.append((max(hit), ts, True))
        else:
            out += [(s, ts, False) for s in hit]
        first = False
    return out


# ------------------------------------------------------------------ the big picture
def build(store, now, statuses):
    posts = store.posts
    live = store.live()
    curves = {pid: curve(store, pid, now) for pid, p in live.items() if p.get("posted")}
    usuals = {pl: usual(curves, pl, posts=posts) for pl in util.PLATFORMS}
    acc = store.accounts()
    out = {"platforms": {}, "curves": curves, "usual": usuals}
    track_start = None
    for pl in util.PLATFORMS:
        pp = platform_points(store, pl)
        mine = [p for p in live.values() if p["platform"] == pl]
        latest = acc.get(pl, [])[-1][1] if acc.get(pl) else {}
        first_hist = min((pts[1][0] for pts in pp.values() if len(pts) > 1), default=None)
        if first_hist and (track_start is None or first_hist < track_start):
            track_start = first_hist
        total_now, _ = total_at(pp, posts, now)
        typed = bool(mine) and all(p.get("source") == "typed" for p in mine)
        if typed or not mine:
            g24 = g_prev = g7 = g30 = None
        else:
            g24 = gain(pp, posts, now - dt.timedelta(hours=24), now)
            g_prev = gain(pp, posts, now - dt.timedelta(hours=48), now - dt.timedelta(hours=24))
            g7 = gain(pp, posts, now - dt.timedelta(days=7), now)
            g30 = gain(pp, posts, now - dt.timedelta(days=30), now)
        foll = [(ts, v.get("followers")) for ts, v in acc.get(pl, []) if v.get("followers") is not None]
        f7 = None
        if foll:
            base = [v for ts, v in foll if util.parse(ts) <= now - dt.timedelta(days=7)]
            if base:
                f7 = foll[-1][1] - base[-1]
        out["platforms"][pl] = {
            "posts": len(mine), "total_views": round(total_now) if mine else None,
            "gain_24h": g24, "gain_prev_24h": g_prev, "gain_7d": g7, "gain_30d": g30,
            "followers": latest.get("followers"), "followers_7d": f7,
            "engagement": engagement(mine),
            "daily": daily(pp, posts, now, 60) if mine and not typed else [],
            "typed": typed,
            "since": util.iso(first_hist) if first_hist else None,
            "last_post": max((p["posted"] for p in mine), default=None),
        }
    out["tracking_since"] = util.iso(track_start) if track_start else None
    disc = acc.get("discord", [])
    if disc:
        base = [v.get("followers") for ts, v in disc if util.parse(ts) <= now - dt.timedelta(days=7)]
        out["discord"] = {"members": disc[-1][1].get("followers"),
                          "members_7d": (disc[-1][1].get("followers") - base[-1]) if base and base[-1] is not None
                          and disc[-1][1].get("followers") is not None else None,
                          "first": disc[0][1].get("followers"), "first_ts": disc[0][0]}
    return out


def milestones(store, now, summary):
    """All milestones reached so far: [{key, label, platform, step, ts}]."""
    found = []
    for pl in util.PLATFORMS:
        pp = platform_points(store, pl)
        if not pp:
            continue
        start = min((pts[1][0] for pts in pp.values() if len(pts) > 1), default=now)
        series = total_series(pp, store.posts, now, start, step_h=1)
        for s, ts, early in crossings(series, VIEW_STEPS):
            found.append({"key": f"views:{pl}:{s}", "platform": pl, "step": s, "ts": ts, "before": early,
                          "label": f"{util.NAMES[pl]} passed {util.fmt_int(s)} total views"})
        for pid, pts in pp.items():
            for s, ts, early in crossings([(util.iso(t), v) for t, v in pts[1:]], VIDEO_STEPS):
                found.append({"key": f"video:{pid}:{s}", "platform": pl, "step": s, "ts": ts, "post": pid, "before": early,
                              "label": f"“{util.clean_title(store.posts[pid].get('title'), 48)}” passed {util.fmt_int(s)} views"})
    for pl, rows in store.accounts().items():
        series = [(ts, v.get("followers")) for ts, v in rows]
        word = "members" if pl == "discord" else "subscribers" if pl == "youtube" else "followers"
        for s, ts, early in crossings(series, FOLLOW_STEPS):
            found.append({"key": f"followers:{pl}:{s}", "platform": pl, "step": s, "ts": ts, "before": early,
                          "label": f"{util.NAMES[pl]} reached {util.fmt_int(s)} {word}"})
    found.sort(key=lambda m: m["ts"])
    return found


def progress(summary):
    """Next milestone per app: [{platform, label, value, prev, next, pct}]"""
    out = []
    for pl in util.PLATFORMS:
        s = summary["platforms"].get(pl) or {}
        v = s.get("total_views")
        if v and not s.get("typed"):
            nxt, prv = next_step(v, VIEW_STEPS), prev_step(v, VIEW_STEPS)
            if nxt:
                out.append({"platform": pl, "kind": "views", "value": v, "prev": prv, "next": nxt,
                            "pct": (v - prv) / (nxt - prv)})
        f = s.get("followers")
        if f:
            nxt, prv = next_step(f, FOLLOW_STEPS), prev_step(f, FOLLOW_STEPS)
            if nxt:
                out.append({"platform": pl, "kind": "followers", "value": f, "prev": prv, "next": nxt,
                            "pct": (f - prv) / (nxt - prv)})
    d = summary.get("discord") or {}
    if d.get("members"):
        v = d["members"]
        nxt, prv = next_step(v, FOLLOW_STEPS), prev_step(v, FOLLOW_STEPS)
        if nxt:
            out.append({"platform": "discord", "kind": "members", "value": v, "prev": prv, "next": nxt,
                        "pct": (v - prv) / (nxt - prv)})
    return out


# ------------------------------------------------------------------ insights
def insights(store, now, summary, video_of, groups):
    """Plain-English notes, each tagged with how sure we are:
    OBSERVED (straight from our numbers), EARLY (a pattern from few posts), WATCH (needs attention)."""
    notes = []
    live = store.live()
    curves, usuals = summary["curves"], summary["usual"]
    for pl in util.PLATFORMS:
        s = summary["platforms"][pl]
        if not s["posts"]:
            continue
        name = util.NAMES[pl]
        if s["gain_24h"] is not None and not s.get("typed"):
            line = f"{name}: {util.fmt_signed(s['gain_24h'])} views in the last 24 hours"
            if s["gain_prev_24h"] is not None:
                line += f" ({util.fmt_signed(s['gain_prev_24h'])} the day before)"
            notes.append({"tag": "OBSERVED", "kind": "gain", "platform": pl, "text": line + "."})
    # fastest start in the last 14 days, per app, at the latest shared checkpoint
    recent = [pid for pid, p in live.items() if p.get("posted")
              and util.hours_between(p["posted"], now) <= 24 * 14 and curves.get(pid)]
    by_pl = {}
    for pid in recent:
        by_pl.setdefault(live[pid]["platform"], []).append(pid)
    for pl, pids in by_pl.items():
        if len(pids) < 2:
            continue
        for h in (24, 12, 6, 3):
            have = [pid for pid in pids if h in curves[pid]]
            if len(have) >= 2:
                have.sort(key=lambda pid: -curves[pid][h])
                top, low = have[0], have[-1]
                t = util.clean_title(live[top]["title"], 56)
                notes.append({"tag": "OBSERVED", "kind": "fastest", "platform": pl, "post": top,
                              "text": f"Fastest start on {util.SHORT[pl]}: “{t}” with {util.fmt_int(curves[top][h])} views at {h} hours."})
                if curves[low][h] and curves[top][h] / max(curves[low][h], 1) >= 5:
                    lt = util.clean_title(live[low]["title"], 56)
                    notes.append({"tag": "WATCH", "kind": "slow", "platform": pl, "post": low,
                                  "text": f"“{lt}” had {util.fmt_int(curves[low][h])} views at {h} hours, "
                                          f"{curves[top][h] / max(curves[low][h], 1):.0f}× fewer than the fastest. "
                                          "With this few posts we can't tell why: the title, the first frame and the posting time all differ."})
                break
    # vs usual for the newest post on each app
    for pl in util.PLATFORMS:
        mine = sorted((p for p in live.values() if p["platform"] == pl and p.get("posted")),
                      key=lambda p: p["posted"], reverse=True)
        if not mine:
            continue
        pid = next(k for k, v in live.items() if v is mine[0])
        base = usual(curves, pl, exclude=pid, posts=store.posts)
        vs = versus_usual(curves.get(pid, {}), base)
        if vs:
            h, r, n = vs
            word = "above" if r >= 1.15 else "below" if r <= 0.85 else "in line with"
            notes.append({"tag": "OBSERVED", "kind": "usual", "platform": pl, "post": pid,
                          "text": f"Newest {util.SHORT[pl]} post is {word} your usual at {h} hours "
                                  f"({r:.1f}× the middle of your other {n} posts)."})
    # formats, only with enough posts
    fm = {}
    for pid, p in live.items():
        vid = video_of.get(pid)
        f = (groups.get(vid) or {}).get("format") if vid else None
        if f and 24 in curves.get(pid, {}):
            fm.setdefault((p["platform"], f), []).append(curves[pid][24])
    for pl in util.PLATFORMS:
        have = {f: v for (p, f), v in fm.items() if p == pl and len(v) >= MIN_FORMAT}
        if len(have) >= 2:
            med = {f: statistics.median(v) for f, v in have.items()}
            best = max(med, key=med.get)
            worst = min(med, key=med.get)
            if med[worst] and med[best] / med[worst] >= 1.3:
                notes.append({"tag": "EARLY", "kind": "format", "platform": pl,
                              "text": f"On {util.SHORT[pl]}, {best} clips have a higher middle 24-hour view count "
                                      f"than {worst} ones ({util.fmt_int(med[best])} vs {util.fmt_int(med[worst])}, "
                                      f"{len(have[best])} and {len(have[worst])} posts). A pattern, not proof: test it on purpose."})
    d = summary.get("discord")
    if d and d.get("members") is not None:
        since = util.uk(d["first_ts"]).strftime("%-d %b")
        if d["members"] != d["first"]:
            notes.append({"tag": "OBSERVED", "kind": "discord", "platform": "discord",
                          "text": f"Discord: {util.fmt_int(d['members'])} members, up from {util.fmt_int(d['first'])} on {since}."})
    total_posts = sum(summary["platforms"][pl]["posts"] for pl in util.PLATFORMS)
    if total_posts < 10:
        notes.append({"tag": "EARLY", "kind": "early", "platform": None,
                      "text": f"Early days: {total_posts} public posts so far. “Your usual” needs {MIN_USUAL} posts on an app, "
                              f"and format comparisons wait for {MIN_FORMAT} of each, so most comparisons are still switched off."})
    return notes


# ------------------------------------------------------------------ the post table
def post_rows(store, now, summary, video_of, groups):
    rows = []
    curves = summary["curves"]
    for pid, p in store.posts.items():
        if not p.get("posted") or p.get("status") == "superseded":
            continue
        m = p.get("metrics", {})
        base = usual(curves, p["platform"], exclude=pid, posts=store.posts)
        vs = versus_usual(curves.get(pid, {}), base)
        views = m.get("views")
        eng = None
        if views:
            eng = sum(m.get(k) or 0 for k in ENGAGE_KEYS.get(p["platform"], [])) / views
        g24 = None
        pts = points(store, pid)
        if len(pts) > 1 and p.get("status") == "live":
            a = step_at(pts[1:], now - dt.timedelta(hours=24))
            if util.parse(p["posted"]) >= now - dt.timedelta(hours=24):
                a = 0
            if a is not None and views is not None:
                g24 = views - a
        vid = video_of.get(pid)
        rows.append({
            "id": pid, "platform": p["platform"], "title": p.get("title") or "Untitled",
            "url": p.get("url"), "thumb": p.get("thumb"), "posted": p["posted"],
            "duration_s": p.get("duration_s"), "status": p.get("status"), "source": p.get("source"),
            "video": vid, "format": (groups.get(vid) or {}).get("format") if vid else None,
            "metrics": {k: v for k, v in m.items() if v is not None}, "engagement": eng,
            "gain_24h": g24, "curve": curves.get(pid, {}),
            "vs_usual": {"hours": vs[0], "ratio": round(vs[1], 2), "n": vs[2]} if vs else None,
            "usual": {str(h): v for h, v in base.items()},
            "confirmed": p.get("confirmed"), "numbers_age_h": p.get("numbers_age_h"),
            "history": [[ts, v.get("views")] for ts, v in store.history().get(pid, []) if v.get("views") is not None][-400:],
        })
    rows.sort(key=lambda r: r["posted"], reverse=True)
    return rows
