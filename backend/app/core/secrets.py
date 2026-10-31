"""Reversible encryption for the platform's first (and, deliberately, only) reversibly-stored
secrets: a playground-eligible agent's own copy of its ingest token and its gateway virtual key
(`add-agent-playground`, design.md D2). Every other credential in this codebase is either
hash-only (`Agent.token_hash`, mirroring `Provider`/D4) or an externally-held env-var *name*
(`Provider.key_env`) - this module exists only because spawning a subprocess on an agent's behalf
requires handing it a *usable* secret, which neither of those forms can ever provide back.

Keyed by `Settings.playground_secret_key` (`EVAL_SECRET_KEY`), read once by the caller and passed
in - this module never reads the environment itself, matching every other `Settings`-driven
feature in this codebase. `encrypt`/`decrypt` are the only functions here; nothing else should ever
need to touch a Fernet instance directly."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class PlaygroundSecretsDisabled(Exception):
    """Raised when no `EVAL_SECRET_KEY` is configured - the feature is off, not broken."""


def _fernet(secret_key: str) -> Fernet:
    # EVAL_SECRET_KEY is an operator-chosen passphrase, not necessarily a valid Fernet key (32
    # url-safe-base64 bytes) - derive one deterministically so any non-empty string works, the same
    # tolerance the platform already extends to every other operator-supplied env var.
    derived = hashlib.sha256(secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(plaintext: str, *, secret_key: str | None) -> bytes:
    if not secret_key:
        raise PlaygroundSecretsDisabled("EVAL_SECRET_KEY is not configured; playground credential storage is off")
    return _fernet(secret_key).encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes, *, secret_key: str | None) -> str:
    if not secret_key:
        raise PlaygroundSecretsDisabled("EVAL_SECRET_KEY is not configured; playground credential storage is off")
    try:
        return _fernet(secret_key).decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("stored credential could not be decrypted with the configured EVAL_SECRET_KEY") from exc
