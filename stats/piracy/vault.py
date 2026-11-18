"""Sign-in tokens (TikTok, Google, Instagram), kept encrypted in data/vault.json.

The repo can be public, so tokens are never stored in plain text. Each service's tokens
are locked with a key derived from that service's own GitHub secret (its client secret),
so no extra secret is needed. Without the secret, nothing in the vault can be read.
"""
import base64
import hashlib
import json

from . import util

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:          # the workflow installs it; tests without it skip the vault
    Fernet = None
    InvalidToken = Exception


def _key(secret, service):
    raw = hashlib.pbkdf2_hmac("sha256", secret.encode(), f"piracy-vault:{service}".encode(), 200_000, 32)
    return base64.urlsafe_b64encode(raw)


class Vault:
    def __init__(self, path):
        self.path = path
        self.data = util.load_json(path, {})
        self.changed = False

    def get(self, service, secret):
        """The stored dict for a service, or None (missing, or the secret changed)."""
        blob = (self.data.get(service) or {}).get("v")
        if not blob or not secret or Fernet is None:
            return None
        try:
            return json.loads(Fernet(_key(secret, service)).decrypt(blob.encode()))
        except (InvalidToken, ValueError):
            return None

    def put(self, service, secret, value, meta=None):
        if Fernet is None:
            raise RuntimeError("the cryptography package is missing (pip install cryptography)")
        token = Fernet(_key(secret, service)).encrypt(json.dumps(value).encode()).decode()
        self.data[service] = {"v": token, **(meta or {})}
        self.changed = True

    def meta(self, service):
        return {k: v for k, v in (self.data.get(service) or {}).items() if k != "v"}

    def save(self):
        if self.changed:
            util.save_json(self.path, self.data)
            self.changed = False
