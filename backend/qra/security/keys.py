"""Envelope encryption for bring-your-own-key storage (WP-12).

A provider key is a bearer credential for someone else's bill. The rules here
are narrow on purpose:

* ciphertext at rest, never plaintext;
* no endpoint returns a key, and no log line contains one — only a fingerprint;
* the plaintext exists in memory for the duration of one provider call.

AES-GCM via ``cryptography`` when it is installed; otherwise an HMAC-based
stream cipher built on hashlib so a deployment without the extra still stores
ciphertext rather than falling back to plaintext. The fallback is authenticated
and clearly marked in the payload so a later migration can re-encrypt.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets

from qra.config import settings


class KeyError_(RuntimeError):
    pass


def _master_key() -> bytes:
    material = settings.secret_key or os.environ.get("QRA_SECRET_KEY")
    if not material:
        raise KeyError_(
            "QRA_SECRET_KEY is not set; provider keys cannot be stored encrypted. "
            "Generate one with `python -c \"import secrets;print(secrets.token_urlsafe(48))\"`."
        )
    return hashlib.sha256(material.encode()).digest()


def _try_aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415

        return AESGCM
    except ImportError:
        return None


def encrypt_secret(plaintext: str) -> str:
    key = _master_key()
    nonce = secrets.token_bytes(12)
    aesgcm = _try_aesgcm()
    if aesgcm is not None:
        blob = aesgcm(key).encrypt(nonce, plaintext.encode(), None)
        payload = {"v": 1, "alg": "aesgcm", "n": base64.b64encode(nonce).decode(),
                   "c": base64.b64encode(blob).decode()}
    else:
        stream = _keystream(key, nonce, len(plaintext.encode()))
        cipher = bytes(a ^ b for a, b in zip(plaintext.encode(), stream, strict=True))
        tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        payload = {"v": 1, "alg": "hmac-ctr", "n": base64.b64encode(nonce).decode(),
                   "c": base64.b64encode(cipher).decode(),
                   "t": base64.b64encode(tag).decode()}
    return json.dumps(payload, separators=(",", ":"))


def decrypt_secret(ciphertext: str) -> str:
    key = _master_key()
    payload = json.loads(ciphertext)
    nonce = base64.b64decode(payload["n"])
    blob = base64.b64decode(payload["c"])
    if payload["alg"] == "aesgcm":
        aesgcm = _try_aesgcm()
        if aesgcm is None:
            raise KeyError_(
                "this key was encrypted with AES-GCM but `cryptography` is not installed"
            )
        return aesgcm(key).decrypt(nonce, blob, None).decode()
    expected = base64.b64decode(payload["t"])
    if not hmac.compare_digest(expected, hmac.new(key, nonce + blob, hashlib.sha256).digest()):
        raise KeyError_("stored key failed its integrity check")
    stream = _keystream(key, nonce, len(blob))
    return bytes(a ^ b for a, b in zip(blob, stream, strict=True)).decode()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """HMAC-SHA256 in counter mode. Only used when AES-GCM is unavailable."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def fingerprint(plaintext: str) -> str:
    """A safe display handle: last four characters plus a short digest.

    Enough for a researcher to recognise which key is stored, useless to anyone
    who obtains the database.
    """
    digest = hashlib.sha256(plaintext.encode()).hexdigest()[:8]
    return f"…{plaintext[-4:]}·{digest}"
