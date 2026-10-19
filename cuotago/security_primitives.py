"""Small auth helpers based on RFC 6238 (HMAC-SHA1 / 30 seconds / six digits)."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlsplit

def new_token():
    return secrets.token_urlsafe(32)

def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def new_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")

def totp(secret, counter, digits=6):
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8), casefold=True)
    raw = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = raw[-1] & 15
    number = (struct.unpack(">I", raw[offset:offset + 4])[0] & 0x7fffffff) % (10 ** digits)
    return str(number).zfill(digits)

def verify_totp(secret, code, *, last_counter=-1, at=None):
    code = (code or "").strip()
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    current = int(time.time() if at is None else at) // 30
    for counter in (current, current - 1, current + 1):
        if counter >= 0 and counter > last_counter and hmac.compare_digest(totp(secret, counter), code):
            return counter
    return None

def provisioning_uri(secret, email, issuer="CuotaGO"):
    return "otpauth://totp/" + quote(issuer + ":" + email, safe="") + "?secret=" + secret + "&issuer=" + quote(issuer) + "&algorithm=SHA1&digits=6&period=30"

def safe_next(value, fallback="/"):
    from urllib.parse import unquote, urlsplit
    if not isinstance(value, str) or not value.startswith('/'):
        return fallback
    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)
    if decoded.startswith('//') or '\\' in decoded or any(ord(c) < 32 for c in decoded):
        return fallback
    parsed = urlsplit(decoded)
    return value if not parsed.scheme and not parsed.netloc else fallback


def encryption_key(master):
    return base64.urlsafe_b64encode(hmac.new(master.encode(), b"cuotago-mfa-v83", hashlib.sha256).digest())

def encrypt_secret(secret, master):
    from cryptography.fernet import Fernet
    return Fernet(encryption_key(master)).encrypt(secret.encode()).decode()

def decrypt_secret(payload, master):
    from cryptography.fernet import Fernet
    return Fernet(encryption_key(master)).decrypt(payload.encode()).decode()
