"""The bot's memory.

data/posts.json            every post ever seen, with its latest good numbers
data/history/posts-*.csv   one row per post per change (append-only, a file per month)
data/history/accounts-*.csv followers and totals per app over time
data/state.json            Discord message ids, alerts already sent, milestones, video groups
data/runs.json             the last 200 runs, for the Status page

Numbers are never overwritten with blanks or zeros when an app fails: the last good value
stays, marked with when it was last confirmed.
"""
import csv
import datetime as dt
import glob
import pathlib
import re

from . import util

POST_METRICS = ["views", "likes", "comments", "shares", "saves", "reach", "avg_view_s", "avg_pct",
                "subs_gained", "watch_min", "full_watch_pct", "follows", "skip_rate"]
HIST_COLS = ["ts", "id", "views", "likes", "comments", "shares", "saves", "reach", "avg_view_s", "avg_pct",
             "subs_gained"]
ACC_COLS = ["ts", "platform", "followers", "total_views", "posts", "likes_total", "channel_views"]
STATIC = ["platform", "title", "url", "posted", "duration_s", "thumb", "source"]


class Store:
    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.posts = util.load_json(self.root / "posts.json", {})
        self.state = util.load_json(self.root / "state.json", {})
        self.runs = util.load_json(self.root / "runs.json", [])
        self._hist = None
        self._acc = None

    # ---------------------------------------------------------------- history files
    def _rows(self, pattern):
        rows = []
        for f in sorted(glob.glob(str(self.root / "history" / pattern))):
            with open(f, newline="", encoding="utf-8") as fh:
                rows += list(csv.DictReader(fh))
        return rows

    def history(self):
        """{post_id: [(ts, {metric: value})...]} sorted by time."""
        if self._hist is None:
            out = {}
            for r in self._rows("posts-*.csv"):
                vals = {k: util.num(r.get(k)) for k in HIST_COLS[2:] if util.num(r.get(k)) is not None}
                out.setdefault(r["id"], []).append((r["ts"], vals))
            for v in out.values():
                v.sort(key=lambda x: x[0])
            self._hist = out
        return self._hist

    def accounts(self):
        """{platform: [(ts, {followers, total_views, posts, ...})...]}"""
        if self._acc is None:
            out = {}
            for r in self._rows("accounts-*.csv"):
                vals = {k: util.num(r.get(k)) for k in ACC_COLS[2:] if util.num(r.get(k)) is not None}
                out.setdefault(r["platform"], []).append((r["ts"], vals))
            for v in out.values():
                v.sort(key=lambda x: x[0])
            self._acc = out
        return self._acc

    def _append(self, kind, cols, ts, row):
        path = self.root / "history" / f"{kind}-{ts[:7]}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(cols)
            w.writerow([_cell(row.get(c)) for c in cols])

    def record_post(self, ts, post_id, vals, force=False):
        """Add a history row if something changed, or the post is young, or it's been 6 hours."""
        hist = self.history().setdefault(post_id, [])
        keep = {k: vals.get(k) for k in HIST_COLS[2:] if vals.get(k) is not None}
        if not keep.get("views") and keep.get("views") != 0:
            return False
        if hist and not force:
            last_ts, last = hist[-1]
            if last_ts >= ts:
                return False
            changed = any(last.get(k) != v for k, v in keep.items())
            posted = (self.posts.get(post_id) or {}).get("posted")
            young = posted and util.hours_between(posted, ts) < 72
            if not changed and not young and util.hours_between(last_ts, ts) < 6:
                return False
            if not changed and util.hours_between(last_ts, ts) < 3:
                return False
        hist.append((ts, keep))
        self._append("posts", HIST_COLS, ts, {"ts": ts, "id": post_id, **keep})
        return True

    def record_account(self, ts, platform, vals):
        hist = self.accounts().setdefault(platform, [])
        keep = {k: vals.get(k) for k in ACC_COLS[2:] if vals.get(k) is not None}
        if not keep:
            return False
        if hist:
            last_ts, last = hist[-1]
            if last_ts >= ts:
                return False
            if all(last.get(k) == v for k, v in keep.items()) and util.hours_between(last_ts, ts) < 6:
                return False
        hist.append((ts, keep))
        self._append("accounts", ACC_COLS, ts, {"ts": ts, "platform": platform, **keep})
        return True

    # ---------------------------------------------------------------- the catalogue of posts
    def merge(self, results, now):
        """Fold this run's posts into the catalogue. Returns the ids seen for the first time."""
        ts = util.iso(now)
        fresh = []
        for res in results:
            if res.status != "ok":
                continue
            seen = set()
            for p in res.posts:
                pid = p["id"]
                seen.add(pid)
                cur = self.posts.get(pid)
                if cur is None:
                    cur = self.posts[pid] = {"first_seen": ts, "metrics": {}}
                    fresh.append(pid)
                for k in STATIC:
                    if p.get(k) is not None:
                        cur[k] = p[k]
                for k in ("format", "video", "numbers_age_h"):
                    if p.get(k) is not None:
                        cur[k] = p[k]
                m = cur.setdefault("metrics", {})
                for k in POST_METRICS:
                    if p.get(k) is not None:
                        m[k] = p[k]
                cur["status"] = "live"
                cur["last_seen"] = ts
                cur["confirmed"] = ts
                when = ts
                if p.get("source") == "typed" and p.get("numbers_age_h") and p.get("posted"):
                    when = util.iso(util.parse(p["posted"]) + dt.timedelta(hours=p["numbers_age_h"]))
                    when = min(when, ts)
                self.record_post(when, pid, m)
            # posts this app no longer lists were made private or deleted (only trust a full answer)
            for pid, cur in self.posts.items():
                if cur.get("platform") == res.platform and cur.get("source") == "api" and pid not in seen \
                        and cur.get("status") == "live":
                    cur["status"] = "gone"
                    cur["gone_since"] = ts
        return fresh

    def live(self, platform=None):
        return {k: v for k, v in self.posts.items()
                if v.get("status") == "live" and (platform is None or v.get("platform") == platform)}

    def save(self):
        util.save_json(self.root / "posts.json", self.posts)
        util.save_json(self.root / "state.json", self.state)
        util.save_json(self.root / "runs.json", self.runs[-200:])


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".") if not v.is_integer() else str(int(v))
    return str(v)


# ------------------------------------------------------------------ grouping the same clip across apps
STOP = {"the", "and", "for", "with", "this", "that", "roblox", "game", "games", "new", "shorts", "short",
        "robloxdev", "robloxstudio", "robloxfyp", "fyp", "piracy", "pirate", "pov", "your", "when", "you",
        "was", "they", "out", "has", "are", "its", "it's", "just", "what", "how", "why", "our", "from"}
FORMAT_WORDS = {
    "Cinematic": ["cutscene", "cinematic", "trailer", "teaser", "intro", "opening"],
    "Devlog": ["devlog", "update", "behind", "making", "how we", "progress", "wip", "building"],
    "Gameplay": ["gameplay", "battle", "combat", "fight", "storm", "sailing", "pvp", "raid", "boss"],
}


def words(text):
    text = re.sub(r"#(\w+)", r"\1", (text or "").lower())
    return {w for w in re.findall(r"[a-z]{3,}", text) if w not in STOP}


def guess_format(text):
    text = (text or "").lower()
    for fmt, keys in FORMAT_WORDS.items():
        if any(k in text for k in keys):
            return fmt
    return None


def group_videos(store, overrides=None):
    """Give each clip one id (V00, V01...) shared by its TikTok, Short and Reel copies."""
    overrides = overrides or {}
    groups = store.state.setdefault("groups", {})        # V00 -> {title, first_posted, words, format}
    video_of = store.state.setdefault("video_of", {})    # post id -> V00
    taken = {(video_of[pid], store.posts[pid]["platform"]) for pid in video_of if pid in store.posts}

    def next_id():
        ids = [int(v[1:]) for v in groups if re.fullmatch(r"V\d+", v)]
        return f"V{(max(ids) + 1) if ids else 0:02d}"

    for pid, p in sorted(store.posts.items(), key=lambda kv: kv[1].get("posted") or ""):
        if not p.get("posted") or (pid not in video_of and p.get("status") != "live"):
            continue
        ov = overrides.get(pid) or overrides.get(p.get("url") or "") or {}
        want = ov.get("video_id") or p.get("video")
        if want:
            video_of[pid] = want
        if pid not in video_of:
            best, best_score = None, 0.0
            for vid, info in groups.items():
                if (vid, p["platform"]) in taken:
                    continue
                gap = abs(util.hours_between(info["first_posted"], p["posted"]))
                if gap > 72:
                    continue
                a, b = words(p.get("title")), set(info.get("words", []))
                score = (len(a & b) / len(a | b) if a | b else 0) + (0.15 if gap <= 24 else 0)
                if score > best_score:
                    best, best_score = vid, score
            video_of[pid] = best if best and best_score >= 0.3 else next_id()
        vid = video_of[pid]
        taken.add((vid, p["platform"]))
        info = groups.setdefault(vid, {"title": util.clean_title(p.get("title"), 60), "first_posted": p["posted"],
                                       "words": [], "format": None})
        if p["posted"] < info["first_posted"]:
            info["first_posted"] = p["posted"]
        info["words"] = sorted(set(info["words"]) | words(p.get("title")))
        if ov.get("title"):
            info["title"] = ov["title"]
        info["format"] = ov.get("format") or p.get("format") or info.get("format") or guess_format(
            " ".join([p.get("title") or "", info["title"]]))
    return video_of, groups
