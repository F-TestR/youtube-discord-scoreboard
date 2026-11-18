"""Every network call goes through here, so tests can swap `transport` for fake answers.

Standard library only. Retries rate limits (429) and server errors, and never puts a
key, token or webhook secret into an error message.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

UA = "PIRACY-stats/2.0 (+https://github.com/F-TestR/youtube-discord-scoreboard)"
SECRET_PARAMS = re.compile(r"((?:key|access_token|refresh_token|client_secret|code|token)=)[^&\s\"']+", re.I)
WEBHOOK = re.compile(r"(webhooks/\d+/)[\w-]+")


class HTTPError(Exception):
    def __init__(self, status, body, url=""):
        self.status = status
        self.body = body or ""
        super().__init__(f"HTTP {status} from {scrub(url.split('?')[0])}: {scrub(self.body[:240])}")


def scrub(text):
    """Blank out anything that looks like a secret."""
    text = SECRET_PARAMS.sub(r"\1[hidden]", str(text))
    return WEBHOOK.sub(r"\1[hidden]", text)


def _urllib(method, url, data, headers, timeout):
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


# Tests replace this with a function (method, url, data, headers, timeout) -> (status, bytes, headers)
transport = _urllib
sleep = time.sleep


def multipart(payload, files):
    """files: [(field_name, filename, bytes, content_type)] -> (body, content_type)."""
    boundary = "piracy" + uuid.uuid4().hex
    out = []
    out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
               f"Content-Type: application/json\r\n\r\n".encode())
    out.append(json.dumps(payload).encode() + b"\r\n")
    for field, name, blob, ctype in files:
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\n'
                   f"Content-Type: {ctype}\r\n\r\n".encode())
        out.append(blob + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def request(method, url, params=None, json_body=None, form=None, files=None, headers=None,
            tries=4, timeout=30, raw=False):
    """JSON in, JSON out (or text with raw=True)."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
    data = None
    if files is not None:
        data, ctype = multipart(json_body or {}, files)
        h["Content-Type"] = ctype
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        h["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    last = None
    for attempt in range(tries):
        try:
            status, body, rh = transport(method, url, data, h, timeout)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
            if attempt < tries - 1:
                sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"couldn't reach {scrub(url.split('?')[0])}: {scrub(e)}") from None
        text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
        if status == 429 and attempt < tries - 1:
            wait = 2.0
            try:
                wait = float(json.loads(text).get("retry_after", wait))
            except Exception:
                try:
                    wait = float((rh or {}).get("Retry-After", wait))
                except Exception:
                    pass
            sleep(min(wait, 60) + 0.25)
            continue
        if status >= 500 and attempt < tries - 1:
            sleep(3 * (attempt + 1))
            continue
        if status >= 400:
            raise HTTPError(status, text, url)
        if raw:
            return text
        return json.loads(text) if text.strip() else None
    raise RuntimeError(f"gave up on {scrub(url.split('?')[0])}: {scrub(last)}")
