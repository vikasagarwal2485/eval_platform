"""OpenTelemetry tracer setup for the Runner's own spans (add-otel-tracing decision 2).

Configured via `Settings.otel_endpoint` (env `EVAL_OTEL_ENDPOINT`). Unset is a graceful no-op -
`traced_span()` then yields `None` and does nothing else. A bad/unreachable endpoint is also
never fatal here: `OTLPSpanExporter` only tries to connect when its background batch processor
actually flushes, and the SDK's own export path swallows and logs that failure rather than
raising it into application code - this module adds one more layer of defense around span
*creation* itself (`traced_span()`'s own try/except) so that even a bug in our instrumentation
code, not just a transport failure, can never affect a run's own result or status.

Deliberately bypasses the OTel API's global `trace.set_tracer_provider()`/`get_tracer()`
registry (which only accepts being set once per process) and instead holds this module's own
`TracerProvider` instance directly - `start_as_current_span()` still participates in the normal
contextvar-based current-span tracking, so nested spans still parent correctly, but
`setup_tracing()` stays safe to call repeatedly (every app instance in a test process, for
example) without "overriding of current TracerProvider is not allowed" warnings.

Two ways to continue a trace a span already started, reflecting what's actually available
(design.md decision 3: only `trace_id` is ever persisted, never a span id):
- `parent=<SpanRef>`: a genuine parent-child edge, when the caller still holds the exact
  `SpanRef` of the span to continue from (same process, same call stack - e.g. a model's warm-up
  span, continued into its first measured request a few lines later).
- `trace_id=<str>`: joins that trace (so a trace-id-keyed query still finds it together with
  everything else from that request), but with a synthetic, non-recorded parent - there is no real
  span id to attach to once only the trace id survived a round trip through storage (e.g. a judge
  call, potentially run much later in a separate stage, reading only `Result.trace_id`).
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from typing import NamedTuple

# Set before importing anything that pulls in `grpc` (the next import does): a process that forks
# after this module's OTLP channel is alive (e.g. a multi-worker server manager forking workers, or
# a reload supervisor) can otherwise have grpc's C-core "poll" engine (the only one available
# outside Linux) spam stderr with "FD from fork parent still in poll list" INFO-level noise -
# harmless, but not something anyone's terminal output should be cluttered with. `setdefault`, not
# an overwrite: an operator who has set these explicitly is left alone. Same fix as
# `agents/eval_agent_sdk/tracing.py`, which actually hits this (an agent process forking a tool
# subprocess) far more often than this one does.
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "1")
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")

from opentelemetry import context as otel_context  # noqa: E402
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # noqa: E402
from opentelemetry.sdk.resources import Resource  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator  # noqa: E402
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context  # noqa: E402

from app.config import Settings  # noqa: E402

log = logging.getLogger(__name__)

_provider: TracerProvider | None = None
_id_generator = RandomIdGenerator()


class SpanRef(NamedTuple):
    """Identifies one already-started-or-finished span, for continuing its trace later."""

    trace_id: str  # 32 lowercase hex chars
    span_id: str  # 16 lowercase hex chars


def setup_tracing(settings: Settings) -> None:
    """Install (or clear) this process's tracer provider. Never raises.

    Shuts down any previously-installed provider first, so repeated calls (every `create_app()` in
    a test process, for example) don't each leak a `BatchSpanProcessor` background thread still
    retrying against an old endpoint."""
    global _provider
    previous, _provider = _provider, None
    if previous is not None:
        try:
            previous.shutdown()
        except Exception:
            log.warning("shutting down the previous tracer provider failed", exc_info=True)
    if not settings.otel_endpoint:
        return
    try:
        provider = TracerProvider(resource=Resource.create({"service.name": "eval-platform-backend"}))
        # A short export deadline: this is best-effort telemetry, not something a shutdown (or an
        # intermittently-down Collector) should ever block noticeably on.
        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, insecure=True, timeout=2)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _provider = provider
    except Exception:
        log.warning("OTel tracer setup failed; tracing disabled for this process", exc_info=True)
        _provider = None


def is_enabled() -> bool:
    return _provider is not None


def _remote_context(trace_id_hex: str, span_id_hex: str | None):
    """A context carrying a non-recording "remote" span, so a brand-new span started under it
    becomes part of `trace_id_hex` even though the span (if any) that originally created that
    trace has long since ended. `span_id_hex` gives a genuine parent-child edge when the caller
    still has it; otherwise a fresh synthetic span id still joins the trace, just with no real
    span to visually nest under. Raises on a malformed id; callers catch that like any other
    span-setup failure."""
    span_context = SpanContext(
        trace_id=int(trace_id_hex, 16),
        span_id=int(span_id_hex, 16) if span_id_hex is not None else _id_generator.generate_span_id(),
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return set_span_in_context(NonRecordingSpan(span_context))


@contextmanager
def traced_span(name: str, *, parent: SpanRef | None = None, trace_id: str | None = None, **attributes):
    """Yields this span's `SpanRef`, or `None` when tracing is disabled or span creation itself
    fails. Exceptions raised by the wrapped code are always re-raised - this never swallows a
    caller's own error, only a failure in the tracing machinery itself.

    Pass at most one of `parent` (a real parent-child edge) or `trace_id` (same-trace only, no
    real parent span) - see the module docstring. Neither: a fresh trace.
    """
    if _provider is None:
        yield None
        return
    detach_token = None
    try:
        if parent is not None:
            detach_token = otel_context.attach(_remote_context(parent.trace_id, parent.span_id))
        elif trace_id is not None:
            detach_token = otel_context.attach(_remote_context(trace_id, None))
        cm = _provider.get_tracer("eval_platform.runner").start_as_current_span(name)
        span = cm.__enter__()
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        ctx = span.get_span_context()
        ref = SpanRef(format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")) if ctx.trace_id else None
    except Exception:
        log.warning("starting trace span %r failed; continuing without a trace id", name, exc_info=True)
        if detach_token is not None:
            otel_context.detach(detach_token)
        yield None
        return
    try:
        yield ref
    except BaseException:
        exc_info = sys.exc_info()
        try:
            cm.__exit__(*exc_info)
        except Exception:
            log.warning("closing trace span %r after an error failed", name, exc_info=True)
        raise
    else:
        try:
            cm.__exit__(None, None, None)
        except Exception:
            log.warning("closing trace span %r failed", name, exc_info=True)
    finally:
        if detach_token is not None:
            otel_context.detach(detach_token)
