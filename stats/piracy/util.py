"""Small helpers: time, files, numbers."""
import datetime as dt
import json
import os
import pathlib
import re
import tempfile

UTC = dt.timezone.utc
try:
    from zoneinfo import ZoneInfo
    UK = ZoneInfo("Europe/London")
except Exception:      # no tz database: fall back to UTC
    UK = UTC

PLATFORMS = ["youtube", "tiktok", "instagram"]
NAMES = {"youtube": "YouTube Shorts", "tiktok": "TikTok", "instagram": "Instagram Reels", "discord": "Discord"}
SHORT = {"youtube": "Shorts", "tiktok": "TikTok", "instagram": "Reels", "discord": "Discord"}
PREFIX = {"youtube": "yt:", "tiktok": "tt:", "instagram": "ig:"}


def platform_of(post_id):
    for p, pre in PREFIX.items():
        if post_id.startswith(pre):
            return p
    return None


def now_utc():
    forced = os.environ.get("BOT_NOW")
    if forced:
        return parse(forced)
    return dt.datetime.now(UTC).replace(microsecond=0)


def parse(s):
    if isinstance(s, dt.datetime):
        return s if s.tzinfo else s.replace(tzinfo=UTC)
    t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def iso(t):
    return parse(t).astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def uk(t):
    return parse(t).astimezone(UK)


def uk_day(t):
    return uk(t).date().isoformat()


def hours_between(a, b):
    return (parse(b) - parse(a)).total_seconds() / 3600


def load_json(path, default):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj, compact=False):
    """Write atomically, so a crash never leaves half a file."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compact else \
        json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fmt_int(v):
    return "—" if v is None else f"{v:,.0f}"


def fmt_short(v):
    if v is None:
        return "—"
    a = abs(v)
    for div, suf in ((1e6, "M"), (1e3, "K")):
        if a >= div:
            x = v / div
            return (f"{x:.1f}".rstrip("0").rstrip(".") if abs(x) < 10 else f"{x:.0f}") + suf
    return f"{v:.0f}"


def fmt_signed(v):
    if v is None:
        return "—"
    if round(v) == 0:
        return "±0"
    return f"+{v:,.0f}" if v > 0 else f"−{abs(v):,.0f}"


def fmt_pct(v, digits=1):
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def clean_title(t, n=70):
    t = re.sub(r"#\w+", "", t or "")
    t = re.sub(r"\s+", " ", t).strip(" -:|")
    return (t[:n - 1].rstrip() + "…") if len(t) > n else (t or "Untitled")


def md_escape(t):
    """Discord markdown: stop titles breaking links or formatting."""
    return re.sub(r"([\\*_`~|>\[\]()])", r"\\\1", t or "")
