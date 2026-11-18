#!/usr/bin/env python3
"""Finish connecting TikTok or YouTube Analytics: swap the one-time code from the sign-in
page for long-lived tokens, and lock them in data/vault.json.

Run by the "Connect an app" workflow:  python stats/connect.py <tiktok|youtube> <code>
"""
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from piracy import collect, net, util, vault as V  # noqa: E402

DATA = pathlib.Path(os.environ.get("STATS_DATA") or HERE / "data")


def main(service, code):
    cfg = util.load_json(HERE / "config.json", {})
    redirect = ((cfg.get("site") or {}).get("url") or "").rstrip("/") + "/connect.html"
    vault = V.Vault(DATA / "vault.json")
    now = util.now_utc()
    code = code.strip()
    if service == "tiktok":
        key, secret = os.environ.get("TIKTOK_CLIENT_KEY", "").strip(), os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
        if not (key and secret):
            sys.exit("Add the TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET secrets first.")
        r = net.request("POST", collect.TT + "oauth/token/", form={
            "client_key": key, "client_secret": secret, "code": code, "grant_type": "authorization_code",
            "redirect_uri": redirect})
        if not r or "access_token" not in r:
            sys.exit(f"TikTok refused the code: {(r or {}).get('error_description') or (r or {}).get('error')}. "
                     "Codes work once and expire quickly: press Connect TikTok again for a new one.")
        collect.store_tiktok(vault, secret, r, now)
        print(f"TikTok connected (scopes: {r.get('scope')}).")
    elif service in ("youtube", "google"):
        cid, secret = os.environ.get("GOOGLE_CLIENT_ID", "").strip(), os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
        if not (cid and secret):
            sys.exit("Add the GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET secrets first.")
        try:
            r = net.request("POST", collect.GOOGLE_TOKEN, form={
                "client_id": cid, "client_secret": secret, "code": code, "grant_type": "authorization_code",
                "redirect_uri": redirect})
        except net.HTTPError as e:
            sys.exit(f"Google refused the code ({e.status}). Codes work once and expire quickly: "
                     "press Connect YouTube Analytics again for a new one.")
        if not r.get("refresh_token"):
            sys.exit("Google didn't hand over a long-lasting sign-in. Remove the app's access at "
                     "myaccount.google.com/permissions, then press Connect YouTube Analytics again.")
        vault.put("google", secret, {"refresh_token": r["refresh_token"], "scope": r.get("scope")},
                  {"connected": util.iso(now), "scope": r.get("scope")})
        print("YouTube Analytics connected.")
    else:
        sys.exit("Choose tiktok or youtube.")
    vault.save()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    try:
        main(sys.argv[1].lower(), sys.argv[2])
    except SystemExit:
        raise
    except Exception as e:
        sys.exit(f"Connecting failed: {net.scrub(e)}")
