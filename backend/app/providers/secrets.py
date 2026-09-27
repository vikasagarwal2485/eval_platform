"""API keys come only from the process environment, read at call time; text is scrubbed of them (design D4).

Nothing here writes a key anywhere. `Redactor` is applied to every piece of text that could reach the database, a
log line, an API response or an export.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Mapping

MARK = "[REDACTED]"
MIN_PARTIAL = 10  # a run of this many consecutive key characters is treated as a leak

# Key-shaped strings (also their masked forms, e.g. "sk-proj-abc***xyz") and auth headers echoed in errors.
_GENERIC = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-*.]{4,}"),
    re.compile(r"sk-[A-Za-z0-9_\-*.]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-*~+/=]{8,}"),
    re.compile(r"""(?i)(x-api-key|api[_-]?key|authorization)(["']?\s*[:=]\s*["']?(?:bearer\s+)?)([^\s"',}]{6,})"""),
]

ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
_KEYISH = re.compile(r"^(sk-|sk_|pk-|key-|AIza)", re.I)


def valid_env_name(name: str) -> tuple[bool, str]:
    """(ok, reason). Only a variable *name* is accepted; key-shaped values are refused with an explanation."""
    if not name:
        return False, "the environment variable name must not be empty"
    if _KEYISH.match(name) or len(name) > 64 or any(c in name for c in " \t\n=\"'"):
        return False, "that looks like an API key; enter only the name of the environment variable that holds it"
    if not ENV_NAME_RE.match(name):
        return False, "use an upper-case environment variable name such as OPENAI_API_KEY"
    return True, ""


class KeyProvider:
    """Reads keys from the environment on every call (so nothing is cached or persisted)."""

    def __init__(self, environ: Mapping[str, str] | None = None):
        self._environ = environ

    @property
    def environ(self) -> Mapping[str, str]:
        return os.environ if self._environ is None else self._environ

    def get(self, key_env: str | None) -> str | None:
        value = self.environ.get(key_env or "")
        return value.strip() if value and value.strip() else None

    def available(self, key_env: str | None) -> bool:
        return self.get(key_env) is not None


class Redactor:
    """Removes secret values (and key-shaped strings) from text."""

    def __init__(self, secrets: Callable[[], Iterable[str]] = lambda: ()):
        self._secrets = secrets

    def redact(self, text: str | None) -> str:
        if not text:
            return text or ""
        secrets = sorted({s for s in self._secrets() if s}, key=len, reverse=True)
        for secret in secrets:
            text = text.replace(secret, MARK)
        for secret in secrets:
            text = self._redact_partial(text, secret)
        text = _GENERIC[0].sub(MARK, text)
        text = _GENERIC[1].sub(MARK, text)
        text = _GENERIC[2].sub(f"Bearer {MARK}", text)
        text = _GENERIC[3].sub(lambda m: f"{m.group(1)}{m.group(2)}{MARK}", text)
        return text

    def redact_exc(self, exc: BaseException) -> str:
        return self.redact(str(exc))

    @staticmethod
    def _redact_partial(text: str, secret: str) -> str:
        """Replace stretches of >= MIN_PARTIAL consecutive characters of the secret (partial echoes)."""
        if len(secret) < MIN_PARTIAL:
            return text
        spans: list[tuple[int, int]] = []
        for i in range(len(secret) - MIN_PARTIAL + 1):
            window = secret[i : i + MIN_PARTIAL]
            start = text.find(window)
            while start != -1:
                lo, hi, k = start, start + MIN_PARTIAL, i
                while lo > 0 and k > 0 and text[lo - 1] == secret[k - 1]:  # grow the match both ways
                    lo, k = lo - 1, k - 1
                k = i + MIN_PARTIAL
                while hi < len(text) and k < len(secret) and text[hi] == secret[k]:
                    hi, k = hi + 1, k + 1
                spans.append((lo, hi))
                start = text.find(window, start + 1)
        for lo, hi in _merge(spans)[::-1]:
            text = text[:lo] + MARK + text[hi:]
        return text


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out
