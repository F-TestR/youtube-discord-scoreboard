"""Builds the website: copies the page files and writes data.json for them to read."""
import datetime as dt
import pathlib
import shutil

from . import analysis, util


def build(out_dir, template_dir, store, now, summary, rows, groups, milestones, progress, notes,
          research, statuses, cfg, connect, run_every_h=1):
    out_dir, template_dir = pathlib.Path(out_dir), pathlib.Path(template_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(template_dir, out_dir)
    start = util.parse(summary.get("tracking_since") or util.iso(now - dt.timedelta(days=7)))
    start = max(start, now - dt.timedelta(days=120))
    series, followers = {}, {}
    for pl in util.PLATFORMS:
        pp = analysis.platform_points(store, pl)
        if pp:
            series[pl] = analysis.total_series(pp, store.posts, now, start.replace(minute=0, second=0), step_h=3)
    for pl, hist in store.accounts().items():
        followers[pl] = [[ts, v.get("followers")] for ts, v in hist if v.get("followers") is not None]
    plats = {}
    for pl, s in summary["platforms"].items():
        plats[pl] = {k: v for k, v in s.items()}
    data = {
        "generated": util.iso(now),
        "next_run": util.iso(now + dt.timedelta(hours=run_every_h)),
        "run_every_h": run_every_h,
        "title": cfg.get("site", {}).get("title", "PIRACY · Social Stats"),
        "repo": cfg.get("repo_url"),
        "status": statuses,
        "summary": {"platforms": plats, "discord": summary.get("discord"),
                    "tracking_since": summary.get("tracking_since")},
        "series": series,
        "followers": followers,
        "posts": rows,
        "groups": {k: {"title": v["title"], "format": v.get("format"), "first_posted": v["first_posted"]}
                   for k, v in groups.items()},
        "milestones": milestones[-60:],
        "progress": progress,
        "insights": notes,
        "research": research,
        "runs": [{"ts": r["ts"], "ok": r.get("ok"), "statuses": r.get("statuses")} for r in store.runs[-72:]],
        "connect": connect,
    }
    util.save_json(out_dir / "data.json", data, compact=True)
    return out_dir
