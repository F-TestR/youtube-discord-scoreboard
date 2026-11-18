#!/usr/bin/env python3
"""One-off: rebuild V2's history from everything the first bot saved (its git history),
so the new charts start on 15 Nov 2026 instead of on the day V2 switched on.

Usage (from the repo root): python3 stats/tools/backfill_v1.py
"""
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from piracy import store as S, util  # noqa: E402

ROOT = HERE.parent


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def main():
    commits = git("log", "--reverse", "--format=%H", "--", "piracy-bot/data/posts.json").split()
    st = S.Store(HERE / "data")
    if st.history():
        print("history already exists, nothing to do")
        return
    n_rows = 0
    for c in commits:
        try:
            posts = json.loads(git("show", f"{c}:piracy-bot/data/posts.json"))
            state = json.loads(git("show", f"{c}:piracy-bot/data/state.json"))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        ts = state.get("last_run") or (posts.get("meta") or [{}, {}])[1].get("value")
        if not ts or not str(ts).endswith("Z"):
            continue
        seen = set()
        for r in posts.get("rows", []):
            pid = r["post_id"]
            plat = {"YouTube Shorts": "youtube", "TikTok": "tiktok", "Instagram Reels": "instagram"}[r["platform"]]
            seen.add(pid)
            cur = st.posts.setdefault(pid, {"first_seen": ts, "metrics": {}})
            src = "typed" if r.get("source") == "typed in" else "api"
            cur.update({"platform": plat, "title": r.get("video") or "Untitled", "url": r.get("url"),
                        "posted": util.iso(r["posted_at"]), "duration_s": r.get("duration_s"), "source": src,
                        "status": "live", "last_seen": ts, "confirmed": ts})
            m = {k: r.get(k) for k in ("views", "likes", "comments", "shares", "saves", "follows", "full_watch_pct",
                                         "avg_watch_s") if r.get(k) is not None}
            if "avg_watch_s" in m:
                m["avg_view_s"] = m.pop("avg_watch_s")
            cur["metrics"].update(m)
            when = ts
            if src == "typed":
                snap = (state.get("snaps", {}).get(pid) or {})
                if snap:
                    h = min(float(k) for k in snap)
                    when = util.iso(util.parse(r["posted_at"]) + __import__("datetime").timedelta(hours=h))
                    cur["numbers_age_h"] = h
            if st.record_post(when, pid, m):
                n_rows += 1
        for pid, cur in st.posts.items():
            if pid.startswith("yt:") and pid not in seen and cur.get("status") == "live":
                cur["status"] = "gone"
                cur["gone_since"] = ts
        members = (state.get("last_views") or {}).get("_members")
        if members is not None:
            st.record_account(ts, "discord", {"followers": members})
        live = [p for p in st.posts.values() if p["platform"] == "youtube" and p["status"] == "live"]
        st.record_account(ts, "youtube", {"total_views": sum(p["metrics"].get("views") or 0 for p in live),
                                          "posts": len(live)})
    st.state["backfilled_from_v1"] = {"commits": len(commits), "rows": n_rows}
    st.save()
    print(f"{len(commits)} commits → {n_rows} history rows, {len(st.posts)} posts")


if __name__ == "__main__":
    main()
