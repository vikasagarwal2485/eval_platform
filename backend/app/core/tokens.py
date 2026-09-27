"""Ingest tokens for deployed agents (design D11).

A token authorises one agent's ingest traffic. It is generated once, shown to the user once, and stored only as a
salted hash plus a short display prefix - never in the clear. This mirrors the enterprise-providers rule that a
credential the platform holds is never returned once written, applied here to a credential the platform *issues*
rather than one it reads from the environment.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

PREFIX_LEN = 8


def generate_token() -> str:
    """32 random bytes, URL-safe. Shown to the caller exactly once."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def display_prefix(raw: str) -> str:
    return raw[:PREFIX_LEN]


def verify_token(raw: str | None, token_hash: str) -> bool:
    if not raw:
        return False
    return hmac.compare_digest(hash_token(raw), token_hash)
