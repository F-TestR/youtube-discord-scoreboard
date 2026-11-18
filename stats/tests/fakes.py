"""A pretend internet for tests: YouTube, TikTok, Google, Discord and the trend bot's board.

FakeWorld holds posts whose views grow over time; `transport` answers the bot's requests
from it, records everything sent to Discord, and can be told to fail an app on purpose.
"""
import datetime as dt
import json
import math
import re
import urllib.parse

UTC = dt.timezone.utc


def t(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


class FakePost:
    def __init__(self, pid, title, posted, final, speed=10.0, likes_rate=0.02, duration=30, private_at=None):
        self.pid, self.title, self.posted, self.final = pid, title, t(posted), final
        self.speed, self.likes_rate, self.duration, self.private_at = speed, likes_rate, duration, private_at and t(private_at)

    def views(self, now):
        h = (now - self.posted).total_seconds() / 3600
        if h < 0:
            return None
        return int(self.final * (1 - math.exp(-h / self.speed)))

    def visible(self, now):
        return now >= self.posted and not (self.private_at and now >= self.private_at)


class FakeWorld:
    def __init__(self, now, youtube=(), tiktok=(), subs=40, members=12, board_csv="", scan=()):
        self.now = t(now) if isinstance(now, str) else now
        self.youtube, self.tiktok = list(youtube), list(tiktok)
        self.subs, self.members = subs, members
        self.board_csv, self.scan = board_csv, list(scan)
        self.fail = set()             # e.g. {"youtube"} to make that app answer 500
        self.sent = []                # every Discord call
        self.discord_messages = {}    # id -> body
        self.next_id = 10 ** 18
        self.calls = []
        self.tt_refresh = "rt-1"

    # -------------------------------------------------------------- the transport
    def transport(self, method, url, data, headers, timeout):
        self.calls.append((method, url))
        u = urllib.parse.urlparse(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        host, path = u.netloc, u.path

        def ok(obj):
            return 200, json.dumps(obj).encode(), {}

        if "googleapis.com" in host and "youtube" in path:
            if "youtube" in self.fail:
                return 500, b'{"error":"boom"}', {}
            if path.endswith("/channels"):
                return ok({"items": [{"id": "UC" + "k" * 22, "snippet": {"title": "ThatOneKull", "customUrl": "@thatonekull",
                                                                       "thumbnails": {"high": {"url": "https://yt3.example/avatar.jpg"}}},
                                      "statistics": ({"subscriberCount": str(self.subs)} if self.subs is not None else {"hiddenSubscriberCount": True}) | {"viewCount": "99999", "videoCount": "12"},
                                      "contentDetails": {"relatedPlaylists": {"uploads": "UU" + "k" * 22}}}]})
            if path.endswith("/playlistItems"):
                vis = [p for p in self.youtube if p.visible(self.now)]
                vis.sort(key=lambda p: p.posted, reverse=True)
                return ok({"items": [{"contentDetails": {"videoId": p.pid}} for p in vis]})
            if path.endswith("/videos"):
                ids = q.get("id", "").split(",")
                items = []
                pool = {p.pid: p for p in self.youtube}
                for s in self.scan:
                    pool.setdefault(s["id"], s)
                for i in ids:
                    p = pool.get(i)
                    if p is None:
                        continue
                    if isinstance(p, dict):
                        items.append({"id": i, "snippet": {"title": p["title"], "channelTitle": p["channel"], "channelId": "UCx",
                                                           "publishedAt": p["published"], "thumbnails": {}},
                                      "statistics": {"viewCount": str(p["views"]), "likeCount": "10", "commentCount": "1"},
                                      "contentDetails": {"duration": f"PT{p['duration_s']}S"}})
                        continue
                    if not p.visible(self.now):
                        continue
                    v = p.views(self.now)
                    items.append({"id": p.pid, "snippet": {"title": p.title, "channelTitle": "ThatOneKull", "channelId": "UC" + "k" * 22,
                                                           "publishedAt": p.posted.isoformat().replace("+00:00", "Z"),
                                                           "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{p.pid}/hqdefault.jpg"}}},
                                  "statistics": {"viewCount": str(v), "likeCount": str(int(v * p.likes_rate)),
                                                 "commentCount": str(int(v * p.likes_rate / 5))},
                                  "contentDetails": {"duration": f"PT{p.duration}S"}})
                return ok({"items": items})
            if path.endswith("/search"):
                return ok({"items": [{"id": {"videoId": s["id"]}} for s in self.scan]})
        if host == "oauth2.googleapis.com":
            return ok({"access_token": "g-access", "expires_in": 3600})
        if "youtubeanalytics" in host:
            if q.get("dimensions") == "video":
                ids = q.get("filters", "").replace("video==", "").split(",")
                rows = [[i, 100, 40.0, 18.0, 61.5, 2, 3] for i in ids if i]
                return ok({"columnHeaders": [{"name": n} for n in ["video", "views", "estimatedMinutesWatched",
                                                                    "averageViewDuration", "averageViewPercentage",
                                                                    "subscribersGained", "shares"]], "rows": rows})
            return ok({"columnHeaders": [{"name": "day"}, {"name": "views"}], "rows": []})
        if host == "open.tiktokapis.com":
            if "tiktok" in self.fail:
                return 500, b'{"error":{"code":"internal_error"}}', {}
            if path.endswith("/oauth/token/"):
                form = urllib.parse.parse_qs((data or b"").decode())
                rt = form.get("refresh_token", [""])[0]
                if form.get("grant_type", [""])[0] == "refresh_token" and rt != self.tt_refresh:
                    return 400, b'{"error":"invalid_grant","error_description":"refresh token reused"}', {}
                n = int(self.tt_refresh.split("-")[1]) + 1
                self.tt_refresh = f"rt-{n}"
                return ok({"access_token": f"at-{n}", "expires_in": 86400, "refresh_token": self.tt_refresh,
                           "refresh_expires_in": 31536000, "open_id": "oid", "scope": "user.info.basic,video.list"})
            if path.endswith("/user/info/"):
                return ok({"data": {"user": {"display_name": "piracy", "follower_count": 230, "likes_count": 900,
                                             "video_count": len(self.tiktok)}}, "error": {"code": "ok"}})
            if path.endswith("/video/list/"):
                vis = [p for p in self.tiktok if p.visible(self.now)]
                vids = [{"id": p.pid, "title": p.title, "create_time": int(p.posted.timestamp()),
                         "share_url": f"https://www.tiktok.com/@piracy/video/{p.pid}", "duration": p.duration,
                         "cover_image_url": "https://p16.example/cover.jpg", "view_count": p.views(self.now),
                         "like_count": int(p.views(self.now) * 0.08), "comment_count": 3, "share_count": 2} for p in vis]
                return ok({"data": {"videos": vids, "cursor": 0, "has_more": False}, "error": {"code": "ok"}})
        if host == "discord.com" and "/invites/" in path:
            return ok({"approximate_member_count": self.members, "approximate_presence_count": 3, "guild": {"name": "PIRACY"}})
        if host == "discord.com" and "/webhooks/" in path:
            body = None
            if data:
                if data[:2] == b"--":
                    m = re.search(rb'name="payload_json"\r\nContent-Type: application/json\r\n\r\n(.*?)\r\n--', data, re.S)
                    body = json.loads(m.group(1))
                    body["_files"] = len(re.findall(rb'name="files\[\d+\]"', data))
                else:
                    body = json.loads(data)
            self.sent.append({"method": method, "path": path, "query": q, "body": body})
            if method == "POST":
                self.next_id += 1
                mid = str(self.next_id)
                self.discord_messages[mid] = body
                return ok({"id": mid, "channel_id": mid if (body or {}).get("thread_name") else "222"})
            if method == "PATCH":
                mid = path.rsplit("/", 1)[1]
                if mid not in self.discord_messages and not mid.startswith("1571"):
                    return 404, b'{"message":"Unknown Message","code":10008}', {}
                self.discord_messages[mid] = body
                return 200, b"", {}
            if method == "DELETE":
                self.discord_messages.pop(path.rsplit("/", 1)[1], None)
                return 204, b"", {}
        if host == "raw.githubusercontent.com":
            return 200, self.board_csv.encode(), {}
        return 404, b'{"message":"not faked: ' + url.encode()[:80] + b'"}', {}
