"""Per-request performance metrics and aggregate statistics.

Ollama reports durations in nanoseconds but not time-to-first-token, which is measured client-side.
Unavailable values are None (never 0) and are excluded from aggregates.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

NS_PER_MS = 1_000_000
# A model load longer than this in a measured request marks it "cold" (warm requests load in ~10-50 ms).
COLD_LOAD_THRESHOLD_NS = 300 * NS_PER_MS

OLLAMA_COUNTERS = (
    "total_duration",
    "load_duration",
    "prompt_eval_count",
    "prompt_eval_duration",
    "eval_count",
    "eval_duration",
)


@dataclass
class StreamCollector:
    """Feed it every streamed chunk; call `finish()` when the stream completes."""

    clock: Any = time.monotonic
    t0: float = field(init=False)
    content: list[str] = field(default_factory=list)
    thinking: list[str] = field(default_factory=list)
    t_first_token: float | None = None
    t_first_answer: float | None = None
    t_end: float | None = None
    final: dict | None = None

    def __post_init__(self) -> None:
        self.t0 = self.clock()

    def feed(self, chunk: dict) -> None:
        now = self.clock()
        msg = chunk.get("message") or {}
        c, t = msg.get("content") or "", msg.get("thinking") or ""
        if (c or t) and self.t_first_token is None:
            self.t_first_token = now
        if c and self.t_first_answer is None:
            self.t_first_answer = now
        if c:
            self.content.append(c)
        if t:
            self.thinking.append(t)
        if chunk.get("done"):
            self.final = chunk
            self.t_end = now

    @property
    def text(self) -> str:
        return "".join(self.content)

    @property
    def thinking_text(self) -> str:
        return "".join(self.thinking)

    def _ms(self, t: float | None) -> float | None:
        return None if t is None else (t - self.t0) * 1000.0

    def finish(self) -> dict:
        """Metrics for a successful request (`final` chunk received)."""
        f = self.final or {}
        raw = {k: f.get(k) for k in OLLAMA_COUNTERS if f.get(k) is not None}
        provider = f.get("_provider")
        if provider is not None:  # an enterprise backend: client-timed, no load phase (design D7)
            m = compute_cloud_metrics(
                raw,
                provider,
                latency_ms=self._ms(self.t_end),
                ttft_ms=self._ms(self.t_first_token),
                ttft_answer_ms=self._ms(self.t_first_answer),
                thinking_chars=len(self.thinking_text),
            )
            m["done_reason"] = f.get("done_reason")
            return m
        m = compute_metrics(
            raw,
            latency_ms=self._ms(self.t_end),
            ttft_ms=self._ms(self.t_first_token),
            ttft_answer_ms=self._ms(self.t_first_answer),
            thinking_chars=len(self.thinking_text),
            answer_chars=len(self.text),
        )
        m["done_reason"] = f.get("done_reason")
        return m

    def failed(self) -> dict:
        """Metrics for a request that errored: only what was actually observed."""
        return {
            "failed": True,
            "latency_ms": None,
            "ttft_ms": self._ms(self.t_first_token),
            "ttft_answer_ms": self._ms(self.t_first_answer),
            "tokens_per_s": None,
            "output_tokens": None,
            "is_cold": False,
            "ollama": {},
        }


def compute_metrics(
    raw: dict,
    *,
    latency_ms: float | None,
    ttft_ms: float | None,
    ttft_answer_ms: float | None,
    thinking_chars: int = 0,
    answer_chars: int = 0,
) -> dict:
    def ms(key: str) -> float | None:
        v = raw.get(key)
        return v / NS_PER_MS if v is not None else None

    eval_count, eval_dur = raw.get("eval_count"), raw.get("eval_duration")
    tps = eval_count / (eval_dur / 1e9) if eval_count and eval_dur else None

    thinking_tokens: int | None = None
    approx = False
    if thinking_chars and eval_count:
        # Ollama does not report thinking tokens separately: apportion by character share and flag it.
        thinking_tokens = round(eval_count * thinking_chars / (thinking_chars + answer_chars))
        approx = True
    elif eval_count is not None:
        thinking_tokens = 0

    load = raw.get("load_duration")
    return {
        "latency_ms": latency_ms,
        "ttft_ms": ttft_ms,
        "ttft_answer_ms": ttft_answer_ms,
        "load_ms": ms("load_duration"),
        "total_ms": ms("total_duration"),
        "prompt_eval_ms": ms("prompt_eval_duration"),
        "eval_ms": ms("eval_duration"),
        "prompt_tokens": raw.get("prompt_eval_count"),
        "output_tokens": eval_count,
        "thinking_tokens": thinking_tokens,
        "thinking_tokens_approx": approx,
        "tokens_per_s": tps,
        "is_cold": bool(load is not None and load > COLD_LOAD_THRESHOLD_NS),
        "ollama": raw,
    }


def compute_cloud_metrics(
    raw: dict,
    provider: dict,
    *,
    latency_ms: float | None,
    ttft_ms: float | None,
    ttft_answer_ms: float | None,
    thinking_chars: int = 0,
) -> dict:
    """Metrics for an enterprise request.

    Token counts come from the provider's usage report; timings are measured by the client. Time spent on failed
    attempts and backoff before the successful request (`retry_wait_ms`) is taken out of latency and time-to-first-token
    and reported separately. Tokens per second is output tokens over the time from the first output token to the end of
    the stream (client-measured). Hidden reasoning tokens (not streamed) are left out of that window, because the time
    they took precedes the first visible token. Load time, evaluation durations and cold starts do not exist here.
    """
    wait = provider.get("retry_wait_ms") or 0.0

    def minus_wait(v: float | None) -> float | None:
        return None if v is None else max(0.0, v - wait)

    latency, ttft, ttft_answer = minus_wait(latency_ms), minus_wait(ttft_ms), minus_wait(ttft_answer_ms)
    eval_count = raw.get("eval_count")
    reasoning = provider.get("reasoning_tokens")

    tps = None
    if eval_count and latency is not None and ttft is not None:
        window_ms = latency - ttft
        hidden = reasoning if reasoning and not thinking_chars else 0  # reasoning that was never streamed
        visible = eval_count - hidden
        if window_ms >= 1.0 and visible > 0:
            tps = visible / (window_ms / 1000.0)

    if reasoning is not None:
        thinking_tokens, approx = int(reasoning), False  # reported by the provider
    elif thinking_chars and eval_count:
        thinking_tokens, approx = None, True  # streamed but not counted separately: cannot be apportioned reliably
    else:
        thinking_tokens, approx = (0 if eval_count is not None else None), False

    return {
        "latency_ms": latency,
        "ttft_ms": ttft,
        "ttft_answer_ms": ttft_answer,
        "load_ms": None,
        "total_ms": None,
        "prompt_eval_ms": None,
        "eval_ms": None,
        "prompt_tokens": raw.get("prompt_eval_count"),
        "output_tokens": eval_count,
        "thinking_tokens": thinking_tokens,
        "thinking_tokens_approx": approx,
        "tokens_per_s": tps,
        "tokens_per_s_source": "client",
        "is_cold": False,
        "is_cloud": True,
        "provider": provider.get("provider"),
        "provider_kind": provider.get("kind"),
        "model_version": provider.get("model_version"),
        "attempts": provider.get("attempts", 1),
        "retry_wait_ms": wait,
        "params_applied": provider.get("params_applied", {}),
        "params_ignored": provider.get("params_ignored", []),
        "finish_reason": provider.get("finish_reason"),
        "ollama": raw,
    }


# ------------------------------------------------------------------ aggregate statistics
def percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (same convention as numpy's default). q in [0, 100]."""
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def describe(values: list[float | None]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "median": None, "p95": None, "min": None, "max": None, "stdev": None}
    return {
        "n": len(vals),
        "mean": statistics.fmean(vals),
        "median": statistics.median(vals),
        "p95": percentile(vals, 95),
        "min": min(vals),
        "max": max(vals),
        "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0,
    }


def perf_stats(rows: list[Any], *, include_cold: bool = False) -> dict:
    """Aggregate Result-like rows (attrs: status, is_cold, latency_ms, ttft_ms, tokens_per_s, output_tokens, metrics).

    Cold requests are excluded unless include_cold. Failed requests never contribute.
    """
    ok = [r for r in rows if r.status == "ok"]
    warm = [r for r in ok if include_cold or not r.is_cold]
    loads = [r.metrics.get("load_ms") for r in ok if r.is_cold]
    return {
        "requests": len(rows),
        "warm_requests": len([r for r in ok if not r.is_cold]),
        "cold_requests": len([r for r in ok if r.is_cold]),
        "latency_ms": describe([r.latency_ms for r in warm]),
        "ttft_ms": describe([r.ttft_ms for r in warm]),
        "tokens_per_s": describe([r.tokens_per_s for r in warm]),
        "output_tokens": describe([r.output_tokens for r in warm]),
        "cold_load_ms": describe(loads),
    }
