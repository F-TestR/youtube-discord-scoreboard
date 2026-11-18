"""Where the numbers come from. Each collector returns a Result and never raises:
a failure becomes status "error" with a plain-English message, and the run carries on
with that app's last good numbers.
"""
import csv
import datetime as dt
import re

from . import net, util

YT = "https://www.googleapis.com/youtube/v3/"
YTA = "https://youtubeanalytics.googleapis.com/v2/reports"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
TT = "https://open.tiktokapis.com/v2/"
DISCORD = "https://discord.com/api/v10/"


class Result:
    def __init__(self, platform, status="ok", message="", posts=None, account=None, extra=None):
        self.platform = platform
        self.status = status            # ok | error | not_connected | partial
        self.message = message
        self.posts = posts or []
        self.account = account or {}
        self.extra = extra or {}

    def __repr__(self):
        return f"<{self.platform} {self.status} {len(self.posts)} posts {self.message[:60]}>"


def _post(platform, raw_id, **kw):
    p = {"id": util.PREFIX[platform] + str(raw_id), "platform": platform, "title": "", "url": None,
         "posted": None, "duration_s": None, "thumb": None, "source": "api"}
    p.update({k: v for k, v in kw.items()})
    return p


# ------------------------------------------------------------------ YouTube (API key)
def iso_duration(s):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def youtube_videos(key, ids):
    out = []
    for i in range(0, len(ids), 50):
        r = net.request("GET", YT + "videos", {"part": "snippet,statistics,contentDetails",
                                               "id": ",".join(ids[i:i + 50]), "key": key}) or {}
        for it in r.get("items", []):
            sn, st = it.get("snippet", {}), it.get("statistics", {})
            th = sn.get("thumbnails", {})
            thumb = (th.get("maxres") or th.get("high") or th.get("medium") or th.get("default") or {}).get("url")
            out.append({"id": it["id"], "title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                        "channel_id": sn.get("channelId", ""), "published": sn.get("publishedAt"),
                        "duration_s": iso_duration(it.get("contentDetails", {}).get("duration")),
                        "views": util.num(st.get("viewCount")), "likes": util.num(st.get("likeCount")),
                        "comments": util.num(st.get("commentCount")), "thumb": thumb})
    return out


def _playlist_ids(key, playlist, limit=200):
    ids, page = [], None
    while len(ids) < limit:
        p = {"part": "contentDetails", "playlistId": playlist, "maxResults": 50, "key": key}
        if page:
            p["pageToken"] = page
        r = net.request("GET", YT + "playlistItems", p) or {}
        ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    return ids


def youtube(key, channel, shorts_max_s=180):
    if not key:
        return Result("youtube", "not_connected", "Add the YOUTUBE_API_KEY secret.")
    if not channel or channel.startswith("@YOUR"):
        return Result("youtube", "not_connected", "Put the YouTube handle in stats/config.json.")
    try:
        p = {"part": "snippet,statistics,contentDetails", "key": key}
        if channel.startswith("UC") and len(channel) == 24:
            p["id"] = channel
        else:
            p["forHandle"] = channel if channel.startswith("@") else "@" + channel
        items = (net.request("GET", YT + "channels", p) or {}).get("items") or []
        if not items:
            return Result("youtube", "error", f"YouTube can't find the channel {channel}.")
        ch = items[0]
        cid, st, sn = ch["id"], ch.get("statistics", {}), ch.get("snippet", {})
        # Shorts: YouTube's own Shorts list for the channel when it answers, else all uploads
        # filtered by length (a Short is at most 3 minutes)
        how = "Shorts list"
        try:
            ids = _playlist_ids(key, "UUSH" + cid[2:])
        except net.HTTPError:
            ids = []
        if not ids:
            how = "uploads up to 3 min"
            ids = _playlist_ids(key, ch["contentDetails"]["relatedPlaylists"]["uploads"])
        posts = []
        for v in youtube_videos(key, ids):
            if how != "Shorts list" and (v["duration_s"] is None or v["duration_s"] > shorts_max_s):
                continue
            posts.append(_post("youtube", v["id"], title=v["title"], url=f"https://www.youtube.com/shorts/{v['id']}",
                               posted=v["published"], duration_s=v["duration_s"], thumb=v["thumb"],
                               views=v["views"], likes=v["likes"], comments=v["comments"]))
        th = sn.get("thumbnails", {})
        account = {"followers": None if st.get("hiddenSubscriberCount") else util.num(st.get("subscriberCount")),
                   "channel_views": util.num(st.get("viewCount")), "videos": util.num(st.get("videoCount")),
                   "name": sn.get("title"), "handle": sn.get("customUrl"), "id": cid,
                   "avatar": (th.get("high") or th.get("medium") or th.get("default") or {}).get("url")}
        return Result("youtube", "ok", f"{len(posts)} Shorts ({how})", posts, account)
    except Exception as e:
        return Result("youtube", "error", f"YouTube didn't answer: {net.scrub(e)}")


# ------------------------------------------------------------------ YouTube Analytics (Google sign-in)
def google_access(vault, client_id, client_secret):
    tok = vault.get("google", client_secret)
    if not tok or not client_id:
        return None
    r = net.request("POST", GOOGLE_TOKEN, form={"client_id": client_id, "client_secret": client_secret,
                                                "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    return r["access_token"]


def youtube_analytics(vault, client_id, client_secret, video_ids, today):
    """Watch time, % viewed and subscribers gained per Short. Optional extra."""
    if not (client_id and client_secret) or not vault.get("google", client_secret):
        return Result("youtube_analytics", "not_connected", "Not connected yet. It adds watch time, % viewed and subscribers gained for each Short.")
    try:
        access = google_access(vault, client_id, client_secret)
        h = {"Authorization": f"Bearer {access}"}
        per_video = {}
        metrics = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,shares"
        for i in range(0, len(video_ids), 200):
            chunk = video_ids[i:i + 200]
            if not chunk:
                continue
            r = net.request("GET", YTA, {"ids": "channel==MINE", "startDate": "2020-01-01", "endDate": today,
                                         "metrics": metrics, "dimensions": "video",
                                         "filters": "video==" + ",".join(chunk), "maxResults": 200,
                                         "sort": "-views"}, headers=h) or {}
            cols = [c["name"] for c in r.get("columnHeaders", [])]
            for row in r.get("rows", []) or []:
                d = dict(zip(cols, row))
                per_video["yt:" + d["video"]] = {
                    "watch_min": util.num(d.get("estimatedMinutesWatched")),
                    "avg_view_s": util.num(d.get("averageViewDuration")),
                    "avg_pct": (util.num(d.get("averageViewPercentage")) or 0) / 100 if d.get("averageViewPercentage") is not None else None,
                    "subs_gained": util.num(d.get("subscribersGained")),
                    "shares": util.num(d.get("shares")),
                }
        start = (dt.date.fromisoformat(today) - dt.timedelta(days=90)).isoformat()
        r = net.request("GET", YTA, {"ids": "channel==MINE", "startDate": start, "endDate": today,
                                     "metrics": "views,subscribersGained,subscribersLost,estimatedMinutesWatched",
                                     "dimensions": "day", "sort": "day"}, headers=h) or {}
        cols = [c["name"] for c in r.get("columnHeaders", [])]
        daily = [dict(zip(cols, row)) for row in (r.get("rows") or [])]
        return Result("youtube_analytics", "ok", f"watch data for {len(per_video)} Shorts",
                      extra={"per_video": per_video, "daily": daily})
    except Exception as e:
        msg = net.scrub(e)
        if "invalid_grant" in msg:
            msg = "The YouTube Analytics sign-in has expired or was removed. Connect it again on the Status page."
        return Result("youtube_analytics", "error", f"YouTube Analytics didn't answer: {msg}")


# ------------------------------------------------------------------ TikTok (Display API)
def _tt_check(r):
    err = (r or {}).get("error") or {}
    if err and err.get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok said {err.get('code')}: {err.get('message', '')[:160]}")
    return (r or {}).get("data") or {}


def tiktok_token(vault, client_key, client_secret, now):
    """A working access token, renewing (and re-saving) the rotating refresh token when needed."""
    tok = vault.get("tiktok", client_secret)
    if not tok:
        return None, None
    if tok.get("access_token") and util.parse(tok.get("expires_at", "1970-01-01T00:00:00Z")) > now + dt.timedelta(minutes=15):
        return tok["access_token"], tok
    r = net.request("POST", TT + "oauth/token/", form={"client_key": client_key, "client_secret": client_secret,
                                                     "grant_type": "refresh_token",
                                                     "refresh_token": tok["refresh_token"]})
    if not r or "access_token" not in r:
        raise RuntimeError(f"TikTok wouldn't renew the sign-in: {(r or {}).get('error_description') or (r or {}).get('error')}")
    tok = store_tiktok(vault, client_secret, r, now)
    vault.save()           # save straight away: the old refresh token no longer works
    return tok["access_token"], tok


def store_tiktok(vault, client_secret, r, now):
    tok = {"access_token": r["access_token"], "refresh_token": r["refresh_token"],
           "expires_at": util.iso(now + dt.timedelta(seconds=int(r.get("expires_in", 3600)))),
           "refresh_expires_at": util.iso(now + dt.timedelta(seconds=int(r.get("refresh_expires_in", 86400 * 180)))),
           "open_id": r.get("open_id"), "scope": r.get("scope")}
    vault.put("tiktok", client_secret, tok, {"refresh_expires_at": tok["refresh_expires_at"],
                                             "connected": util.iso(now), "scope": tok["scope"]})
    return tok


def tiktok(vault, client_key, client_secret, now):
    if not (client_key and client_secret):
        return Result("tiktok", "not_connected", "Not connected yet, so TikTok numbers come from the typed-in sheet.")
    try:
        access, tok = tiktok_token(vault, client_key, client_secret, now)
        if not access:
            return Result("tiktok", "not_connected", "The keys are in place. One step left: press Connect TikTok below.")
        h = {"Authorization": f"Bearer {access}"}
        user = _tt_check(net.request("GET", TT + "user/info/", {
            "fields": "open_id,display_name,avatar_url,follower_count,following_count,likes_count,video_count"},
            headers=h)).get("user", {})
        posts, cursor = [], None
        fields = "id,title,video_description,create_time,cover_image_url,share_url,duration,view_count,like_count,comment_count,share_count"
        for _ in range(10):
            body = {"max_count": 20}
            if cursor:
                body["cursor"] = cursor
            d = _tt_check(net.request("POST", TT + "video/list/", {"fields": fields}, json_body=body, headers=h))
            for v in d.get("videos", []):
                title = (v.get("title") or v.get("video_description") or "").strip().split("\n")[0]
                posts.append(_post("tiktok", v["id"], title=title or "TikTok", url=v.get("share_url"),
                                   posted=util.iso(dt.datetime.fromtimestamp(int(v["create_time"]), util.UTC)),
                                   duration_s=util.num(v.get("duration")), thumb=v.get("cover_image_url"),
                                   views=util.num(v.get("view_count")), likes=util.num(v.get("like_count")),
                                   comments=util.num(v.get("comment_count")), shares=util.num(v.get("share_count"))))
            cursor = d.get("cursor")
            if not d.get("has_more"):
                break
        account = {"followers": util.num(user.get("follower_count")), "likes_total": util.num(user.get("likes_count")),
                   "videos": util.num(user.get("video_count")), "name": user.get("display_name"),
                   "avatar": user.get("avatar_url"),
                   "token_expires": tok.get("refresh_expires_at") if tok else None}
        return Result("tiktok", "ok", f"{len(posts)} TikToks", posts, account)
    except Exception as e:
        msg = net.scrub(e)
        if "invalid_grant" in msg or "refresh_token" in msg.lower():
            msg = "The TikTok sign-in has expired. Connect TikTok again on the Status page."
        return Result("tiktok", "error", f"TikTok didn't answer: {msg}")


# ------------------------------------------------------------------ Instagram (API with Instagram Login)
def instagram_token(vault, secret_token, now):
    """The newest token: a renewed one from the vault, else the secret. Renews weekly."""
    if not secret_token:
        return None, None
    stored = vault.get("instagram", secret_token) or {}
    token = stored.get("token") or secret_token
    renewed = stored.get("renewed") or util.iso(now)
    note = None
    if util.hours_between(renewed, now) >= 24 * 7:
        try:
            r = net.request("GET", "https://graph.instagram.com/refresh_access_token",
                            {"grant_type": "ig_refresh_token", "access_token": token})
            token = r["access_token"]
            renewed = util.iso(now)
        except Exception as e:
            note = f"couldn't renew the Instagram sign-in ({net.scrub(e)[:120]})"
    vault.put("instagram", secret_token, {"token": token, "renewed": renewed},
              {"renewed": renewed, "expires": util.iso(util.parse(renewed) + dt.timedelta(days=60))})
    return token, note


def instagram(vault, secret_token, now, version="v24.0"):
    if not secret_token:
        return Result("instagram", "not_connected", "Not connected yet.")
    try:
        token, note = instagram_token(vault, secret_token, now)
        base = f"https://graph.instagram.com/{version}/"
        me = net.request("GET", base + "me", {"fields": "username,followers_count,media_count,profile_picture_url",
                                              "access_token": token}) or {}
        media = net.request("GET", base + "me/media", {
            "fields": "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count,thumbnail_url",
            "limit": 50, "access_token": token}) or {}
        posts = []
        for m in media.get("data", []):
            if m.get("media_product_type") != "REELS":
                continue
            ins = {}
            for metrics in (["views", "reach", "likes", "comments", "shares", "saved", "total_interactions"],
                            ["ig_reels_avg_watch_time"], ["reels_skip_rate"]):
                try:
                    r = net.request("GET", base + f"{m['id']}/insights", {"metric": ",".join(metrics),
                                                                         "access_token": token}) or {}
                    for d in r.get("data", []):
                        tv = d.get("total_value") or {}
                        vals = d.get("values") or [{}]
                        ins[d.get("name")] = tv.get("value", vals[0].get("value"))
                except net.HTTPError:
                    continue
            avg = util.num(ins.get("ig_reels_avg_watch_time"))
            skip = util.num(ins.get("reels_skip_rate"))
            caption = (m.get("caption") or "").strip()
            posts.append(_post("instagram", m["id"], title=caption.split("\n")[0][:120] or "Reel",
                               url=m.get("permalink"), posted=util.iso(m.get("timestamp")),
                               thumb=m.get("thumbnail_url"), views=util.num(ins.get("views")),
                               reach=util.num(ins.get("reach")),
                               likes=util.num(ins.get("likes", m.get("like_count"))),
                               comments=util.num(ins.get("comments", m.get("comments_count"))),
                               shares=util.num(ins.get("shares")), saves=util.num(ins.get("saved")),
                               avg_view_s=avg / 1000 if avg is not None else None,
                               skip_rate=(skip / 100 if skip is not None and skip > 1 else skip)))
        account = {"followers": util.num(me.get("followers_count")), "videos": util.num(me.get("media_count")),
                   "name": me.get("username"), "avatar": me.get("profile_picture_url")}
        return Result("instagram", "ok", f"{len(posts)} Reels" + (f"; {note}" if note else ""), posts, account)
    except Exception as e:
        return Result("instagram", "error", f"Instagram didn't answer: {net.scrub(e)}")


# ------------------------------------------------------------------ Discord member count
def discord(invite_code):
    if not invite_code:
        return Result("discord", "not_connected", "Put a permanent invite code in stats/config.json.")
    try:
        r = net.request("GET", DISCORD + f"invites/{invite_code}", {"with_counts": "true"}) or {}
        return Result("discord", "ok", "Member count from the invite link.", account={
            "followers": util.num(r.get("approximate_member_count")),
            "online": util.num(r.get("approximate_presence_count")),
            "name": (r.get("guild") or {}).get("name")})
    except Exception as e:
        return Result("discord", "error", f"Couldn't read the Discord member count: {net.scrub(e)}")


# ------------------------------------------------------------------ typed-in numbers (fallback)
PLATFORM_WORDS = {"tiktok": "tiktok", "tt": "tiktok", "instagram": "instagram", "ig": "instagram",
                  "reels": "instagram", "instagram reels": "instagram", "youtube": "youtube", "yt": "youtube",
                  "shorts": "youtube", "youtube shorts": "youtube"}


def label_hours(label):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|d|day|days)\b", (label or "").lower())
    if not m:
        return None
    x = float(m.group(1))
    return x * 24 if m.group(2).startswith("d") else x


def _pct(v):
    s = str(v or "").strip()
    if not s:
        return None
    x = util.num(s.rstrip("%"))
    if x is None:
        return None
    return x / 100 if s.endswith("%") or x > 1 else x


def _uk_time(s):
    s = s.strip()
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            t = dt.datetime.strptime(s, f)
            if "%H" not in f:
                t = t.replace(hour=12)
            return util.iso(t.replace(tzinfo=util.UK))
        except ValueError:
            continue
    raise ValueError(f"can't read the date '{s}' (use 2026-11-15 or 2026-11-15 18:00)")


def manual(path):
    """manual/posts.csv: numbers typed in by hand (only needed when an app isn't connected)."""
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
        platform = PLATFORM_WORDS.get(r.get("platform", "").lower())
        if not platform:
            problems.append(f"manual/posts.csv line {i}: unknown app '{r.get('platform')}'")
            continue
        try:
            posted = _uk_time(r.get("posted", ""))
        except ValueError as e:
            problems.append(f"manual/posts.csv line {i}: {e}")
            continue
        link = r.get("link", "")
        m = re.search(r"/video/(\d+)", link) or re.search(r"/reel/([\w-]+)", link) or re.search(r"shorts/([\w-]+)", link)
        key = m.group(1) if m else re.sub(r"[^a-z0-9]+", "-", f"{posted[:10]}-{r.get('title', '')}".lower()).strip("-")[:60]
        posts.append(_post(platform, key, title=r.get("title") or "Untitled", url=link or None, posted=posted,
                           duration_s=util.num(r.get("duration_s")), views=util.num(r.get("views")),
                           likes=util.num(r.get("likes")), comments=util.num(r.get("comments")),
                           shares=util.num(r.get("shares")), saves=util.num(r.get("saves")),
                           follows=util.num(r.get("follows")), avg_view_s=util.num(r.get("avg_watch_s")),
                           full_watch_pct=_pct(r.get("full_watch_pct")), format=r.get("format") or None,
                           video=r.get("video_id") or None, source="typed",
                           numbers_age_h=label_hours(r.get("numbers_from"))))
    return posts, problems
