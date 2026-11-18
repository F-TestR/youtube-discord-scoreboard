#!/usr/bin/env python3
"""Draw Discord messages (Components V2) roughly as Discord shows them, for checking layouts.
Usage: python3 discord_preview.py messages.json out.html   (messages: [{"body": ..., "image": path}])"""
import html
import json
import re
import sys

CSS = """
body{margin:0;background:#313338;font:16px/1.375 'gg sans','Noto Sans','Helvetica Neue',Arial,sans-serif;color:#DBDEE1}
.wrap{width:760px;padding:16px 16px 24px}
.msg{display:flex;gap:16px;margin:0 0 22px}
.av{width:40px;height:40px;border-radius:50%;background:#0B1F27;flex:none;display:grid;place-items:center;color:#36C2B4;font:700 20px Georgia}
.name{font-weight:600;color:#F2F3F5}.app{background:#5865F2;color:#fff;font-size:10px;font-weight:700;padding:1px 4px;border-radius:3px;margin:0 6px;vertical-align:2px}
.time{color:#949BA4;font-size:12px}
.container{border-radius:8px;background:#2B2D31;border:1px solid #3F4147;padding:16px;margin-top:6px;max-width:600px;display:grid;gap:8px;position:relative}
.container::before{content:"";position:absolute;left:-1px;top:-1px;bottom:-1px;width:4px;border-radius:8px 0 0 8px;background:var(--acc)}
.text p{margin:0}.text h2{font-size:20px;margin:0;color:#F2F3F5}.text h3{font-size:16px;margin:0;color:#F2F3F5}
.sub{color:#949BA4;font-size:13px}
.section{display:flex;gap:16px;justify-content:space-between}.section .thumb{width:85px;height:85px;border-radius:8px;background:#1E1F22;flex:none;object-fit:cover}
.sep{border-top:1px solid #3F4147;margin:4px 0}.sep.noline{border:0}
.gallery img{width:100%;border-radius:8px;display:block}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.btn{background:#4E5058;color:#fff;border-radius:3px;padding:2px 16px;height:32px;display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:500}
a{color:#00A8FC;text-decoration:none}code{background:#1E1F22;padding:0 4px;border-radius:4px;font-size:14px}
.ts{background:#3D4048;border-radius:3px;padding:0 2px}
"""


def md(t):
    t = html.escape(t)
    t = re.sub(r"&lt;t:(\d+):(\w)&gt;", r'<span class="ts">12 minutes ago</span>', t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', t.replace("\\(", "(").replace("\\)", ")"))
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)\*", r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    out = []
    for line in t.split("\n"):
        if line.startswith("## "):
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("-# "):
            out.append(f'<p class="sub">{line[3:]}</p>')
        else:
            out.append(f"<p>{line or '&nbsp;'}</p>")
    return "".join(out)


def comp(c, images):
    t = c["type"]
    if t == 17:
        acc = "#%06X" % c.get("accent_color", 0)
        return f'<div class="container" style="--acc:{acc}">' + "".join(comp(x, images) for x in c["components"]) + "</div>"
    if t == 10:
        return f'<div class="text">{md(c["content"])}</div>'
    if t == 9:
        acc = c["accessory"]
        right = f'<img class="thumb" src="{html.escape(images.get(acc["media"]["url"], acc["media"]["url"]))}">' if acc["type"] == 11 else ""
        return '<div class="section"><div>' + "".join(comp(x, images) for x in c["components"]) + f"</div>{right}</div>"
    if t == 14:
        return f'<div class="sep{"" if c.get("divider", True) else " noline"}"></div>'
    if t == 12:
        return '<div class="gallery">' + "".join(f'<img src="{html.escape(images.get(i["media"]["url"], i["media"]["url"]))}">' for i in c["items"]) + "</div>"
    if t == 1:
        return '<div class="row">' + "".join(f'<span class="btn">{b.get("emoji", {}).get("name", "")} {html.escape(b["label"])} ↗</span>' for b in c["components"]) + "</div>"
    return ""


def page(messages):
    body = []
    for m in messages:
        images = m.get("images", {})
        comps = "".join(comp(c, images) for c in m["body"]["components"])
        body.append(f'<div class="msg"><div class="av">P</div><div><span class="name">PIRACY Stats</span><span class="app">APP</span>'
                    f'<span class="time">Today at 18:07</span>{comps}</div></div>')
    return f"<!doctype html><meta charset=utf-8><style>{CSS}</style><div class=wrap>{''.join(body)}</div>"


if __name__ == "__main__":
    msgs = json.load(open(sys.argv[1]))
    open(sys.argv[2], "w").write(page(msgs))
