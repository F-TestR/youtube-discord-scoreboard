"""Where the numbers come from: YouTube, Instagram, the hand-typed CSV and Discord.

Every network call goes through http(), so the self-test can swap it for fake answers.
Standard library only.
"""
import csv
import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "PIRACY-stats-bot/2.0 (+github actions)"
UTC = dt.timezone.utc
try:
    from zoneinfo import ZoneInfo
    UK = ZoneInfo("Europe/London")
except Exception:  # Windows without tzdata: fall back to UTC
    UK = UTC


class HTTPError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


def http(method, url, params=None, body=None, headers=None, tries=4):
    """JSON in, JSON out. Retries rate limits (429) and server errors."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": UA, **(headers or {})}
    if data is not None:
        h["Content-Type"] = "application/json"
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt < tries - 1:
                try:
                    wait = float(json.loads(raw).get("retry_after", 2))
                except Exception:
                    wait = 2
                time.sleep(min(wait, 30) + 0.5)
                continue
            if e.code >= 500 and attempt < tries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise HTTPError(e.code, raw)
        except urllib.error.URLError:
            if attempt < tries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise


def num(v):
    try:
        return None if v is None or str(v).strip() == "" else float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def iso(t):
    return t.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


# ------------------------------------------------------------------ YouTube
YT = "https://www.googleapis.com/youtube/v3/"


def iso_duration(s):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def youtube_videos(key, ids):
    """Public details and counts for any YouTube video ids (50 per call, 1 quota unit each)."""
    out = []
    for i in range(0, len(ids), 50):
        r = http("GET", YT + "videos", {"part": "snippet,statistics,contentDetails",
                                         "id": ",".join(ids[i:i + 50]), "key": key})
        for it in (r or {}).get("items", []):
            sn, st = it.get("snippet", {}), it.get("statistics", {})
            out.append({
                "id": it["id"],
                "title": sn.get("title", ""),
                "channel": sn.get("channelTitle", ""),
                "channel_id": sn.get("channelId", ""),
                "published": sn.get("publishedAt"),
                "duration_s": iso_duration(it.get("contentDetails", {}).get("duration")),
                "views": num(st.get("viewCount")),
                "likes": num(st.get("likeCount")),
                "comments": num(st.get("commentCount")),
            })
    return out


def youtube_channel(key, channel):
    p = {"part": "contentDetails,snippet", "key": key}
    if channel.startswith("UC") and len(channel) == 24:
        p["id"] = channel
    else:
        p["forHandle"] = channel if channel.startswith("@") else "@" + channel
    items = (http("GET", YT + "channels", p) or {}).get("items") or []
    if not items:
        raise RuntimeError(f"no YouTube channel found for {channel}")
    return items[0]["id"], items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def youtube_posts(key, channel, shorts_max_s=180, max_videos=200):
    """Our own Shorts: up to 200 newest uploads with their public counts."""
    channel_id, uploads = youtube_channel(key, channel)
    ids, page = [], None
    while len(ids) < max_videos:
        p = {"part": "contentDetails", "playlistId": uploads, "maxResults": 50, "key": key}
        if page:
            p["pageToken"] = page
        r = http("GET", YT + "playlistItems", p) or {}
        ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    posts = []
    for v in youtube_videos(key, ids):
        if v["duration_s"] is None or v["duration_s"] > shorts_max_s:
            continue
        posts.append({
            "post_id": "yt:" + v["id"], "platform": "YouTube Shorts", "title": v["title"],
            "posted": v["published"], "url": f"https://www.youtube.com/shorts/{v['id']}",
            "duration_s": v["duration_s"], "views": v["views"], "likes": v["likes"],
            "comments": v["comments"], "source": "YouTube API",
        })
    return posts, channel_id


# ------------------------------------------------------------------ Instagram
def instagram_posts(token, version="v24.0", limit=50):
    """Our own Reels with their insights (needs a professional account and a token)."""
    base = f"https://graph.instagram.com/{version}/"
    media = http("GET", base + "me/media", {
        "fields": "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count",
        "limit": limit, "access_token": token})
    posts = []
    for m in (media or {}).get("data", []):
        if m.get("media_product_type") != "REELS":
            continue
        ins = {}

        def ask(metrics):
            r = http("GET", base + f"{m['id']}/insights", {"metric": ",".join(metrics), "access_token": token})
            for d in (r or {}).get("data", []):
                tv = d.get("total_value") or {}
                vals = d.get("values") or [{}]
                ins[d.get("name")] = tv.get("value", vals[0].get("value"))

        core = ["views", "reach", "likes", "comments", "shares", "saved"]
        try:
            ask(core)
        except HTTPError:
            for metric in core:
                try:
                    ask([metric])
                except HTTPError:
                    pass
        for extra in ("ig_reels_avg_watch_time", "reels_skip_rate", "follows"):
            try:
                ask([extra])
            except HTTPError:
                pass
        avg = num(ins.get("ig_reels_avg_watch_time"))
        skip = num(ins.get("reels_skip_rate"))
        caption = (m.get("caption") or "").strip()
        posts.append({
            "post_id": "ig:" + m["id"], "platform": "Instagram Reels",
            "title": caption.split("\n")[0][:120] or "Reel", "posted": m.get("timestamp"),
            "url": m.get("permalink"),
            "views": num(ins.get("views")), "reach": num(ins.get("reach")),
            "likes": num(ins.get("likes", m.get("like_count"))),
            "comments": num(ins.get("comments", m.get("comments_count"))),
            "shares": num(ins.get("shares")), "saves": num(ins.get("saved")),
            "follows": num(ins.get("follows")),
            "avg_watch_s": avg / 1000 if avg is not None else None,   # the API gives milliseconds
            "skip_rate": (skip / 100 if skip is not None and skip > 1 else skip),
            "source": "Instagram API",
        })
    return posts


def instagram_refresh(token):
    return http("GET", "https://graph.instagram.com/refresh_access_token",
                {"grant_type": "ig_refresh_token", "access_token": token})


# ------------------------------------------------------------------ hand-typed numbers
PLATFORM_NAMES = {
    "tiktok": "TikTok", "tt": "TikTok",
    "instagram": "Instagram Reels", "ig": "Instagram Reels", "reels": "Instagram Reels",
    "instagram reels": "Instagram Reels",
    "youtube": "YouTube Shorts", "yt": "YouTube Shorts", "shorts": "YouTube Shorts",
    "youtube shorts": "YouTube Shorts",
}


def pct(v):
    s = str(v or "").strip()
    if not s:
        return None
    if s.endswith("%"):
        x = num(s[:-1])
        return None if x is None else x / 100
    x = num(s)
    return None if x is None else (x / 100 if x > 1 else x)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def uk_time(s):
    """'2026-11-15' or '2026-11-15 18:00' in UK time -> UTC ISO. A bare date counts as midday."""
    s = s.strip()
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            t = dt.datetime.strptime(s, f)
            if "%H" not in f:
                t = t.replace(hour=12)
            return iso(t.replace(tzinfo=UK))
        except ValueError:
            continue
    raise ValueError(f"can't read the date '{s}' (use 2026-11-15 or 2026-11-15 18:00)")


def manual_posts(path):
    """manual/posts.csv: one row per post, typed in by hand (TikTok for now)."""
    posts, problems = [], []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return posts, problems
    for i, r in enumerate(rows, start=2):
        r = {(k or "").strip().lower(): (v if isinstance(v, str) else "").strip() for k, v in r.items() if k}
        if not any(r.values()) or r.get("platform", "").startswith("#"):
            continue
        platform = PLATFORM_NAMES.get(r.get("platform", "").lower())
        if not platform:
            problems.append(f"manual/posts.csv line {i}: unknown platform '{r.get('platform')}'")
            continue
        try:
            posted = uk_time(r.get("posted", ""))
        except ValueError as e:
            problems.append(f"manual/posts.csv line {i}: {e}")
            continue
        unreadable = [k for k in ("views", "likes", "comments", "shares", "saves", "follows", "avg_watch_s")
                      if r.get(k) and num(r.get(k)) is None]
        if unreadable:
            problems.append(f"manual/posts.csv line {i}: can't read {', '.join(unreadable)} (use plain numbers)")
        link = r.get("link", "")
        m = re.search(r"/video/(\d+)", link) or re.search(r"/reel/([\w-]+)", link)
        key = m.group(1) if m else slug(f"{posted[:10]}-{r.get('title', '')}")
        prefix = {"TikTok": "tt:", "Instagram Reels": "ig:", "YouTube Shorts": "yt:"}[platform]
        posts.append({
            "post_id": prefix + key, "platform": platform, "title": r.get("title") or "Untitled",
            "posted": posted, "url": link or None,
            "duration_s": num(r.get("duration_s")),
            "views": num(r.get("views")), "likes": num(r.get("likes")),
            "comments": num(r.get("comments")), "shares": num(r.get("shares")),
            "saves": num(r.get("saves")), "follows": num(r.get("follows")),
            "avg_watch_s": num(r.get("avg_watch_s")), "full_watch_pct": pct(r.get("full_watch_pct")),
            "format": r.get("format") or None, "numbers_from": r.get("numbers_from") or None,
            "video_id": r.get("video_id") or None,
            "source": "typed in",
        })
    return posts, problems


def overrides(path):
    """manual/links.csv: fix which clip a post belongs to, or its format."""
    out = {}
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                r = {(k or "").strip().lower(): (v if isinstance(v, str) else "").strip() for k, v in r.items() if k}
                if r.get("post") and not r["post"].startswith("#"):
                    out[r["post"]] = r
    except FileNotFoundError:
        pass
    return out


# ------------------------------------------------------------------ Discord
DISCORD = "https://discord.com/api/v10/"


def discord_members(invite_code):
    """Member count from any permanent invite code. No bot needed."""
    r = http("GET", DISCORD + f"invites/{invite_code}", {"with_counts": "true"})
    return num((r or {}).get("approximate_member_count")), num((r or {}).get("approximate_presence_count"))


def discord_invite_uses(bot_token, guild_id):
    """Uses of every invite (needs a bot with Manage Server)."""
    r = http("GET", DISCORD + f"guilds/{guild_id}/invites", headers={"Authorization": f"Bot {bot_token}"})
    return {i["code"]: num(i.get("uses")) or 0 for i in (r or [])}
