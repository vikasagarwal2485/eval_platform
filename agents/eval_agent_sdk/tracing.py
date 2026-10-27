"""Real OpenTelemetry instrumentation for the agent SDK (add-otel-tracing decision 5).

This is the trade-off design.md names explicitly: the SDK was "httpx only" until this change: real
spans need `opentelemetry-sdk` and an OTLP exporter as actual dependencies (see
`agents/requirements.txt`), not an optional/soft one like `pyyaml`'s suite-loading convenience.

GenAI semantic-convention attribute names are still marked experimental upstream, so they're
hardcoded as plain strings here rather than imported from `opentelemetry.semconv`'s own
`_incubating` namespace (whose *module path*, not just the attribute names, could move in a future
release) - bump both the pinned package version and these strings together, deliberately, if the
convention stabilizes with renames. Confirmed directly against the pinned package
(`opentelemetry-semantic-conventions==0.66b1`): every `gen_ai.*` constant it carries, including the
ones already used below, is marked `Deprecated: Moved to the OpenTelemetry GenAI semantic
conventions repository` - this means the convention's development moved to its own dedicated repo
(github.com/open-telemetry/semantic-conventions-genai), not that these attribute names themselves
are being retired; they remain exactly what the (now separately-versioned) spec defines, which is
the other reason this module hardcodes the strings rather than importing the deprecated constants.
"""

from __future__ import annotations

import logging
import os

# Set before importing anything that pulls in `grpc` (the next import does): an agent process is
# exactly the kind of process grpc's own fork-safety notes warn about - it can fork (a tool call
# spawning a subprocess, e.g. classifier_router_agent.py's MCP server and reasoning-agent handoff)
# while this module's OTLP channel is alive. Without these, grpc's C-core "poll" engine (the only
# one available outside Linux, so this is not avoidable by picking a different poller) can spam
# stderr with "FD from fork parent still in poll list" INFO-level noise after such a fork - harmless
# to this SDK's own behavior (it isn't fork-unsafe itself; the host agent process is what forks),
# but very much not something an agent's own terminal output should be cluttered with.
# `setdefault`, not an overwrite: an operator who has set these explicitly is left alone.
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "1")
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # noqa: E402
from opentelemetry.sdk.resources import Resource  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: E402

log = logging.getLogger(__name__)

GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
# A closed enum ("chat"/"generate_content"/"text_completion"/"embeddings"/"retrieval"/
# "create_agent"/"invoke_agent"/"execute_tool"/"invoke_workflow") naming the *kind of API call* a
# span represents - complementary to, not a replacement for, `EVAL_KIND` below: every one of
# reasoning_agent's four calls is a chat completion ("chat" here, uniformly), so this alone cannot
# tell classify/plan/solve/verify apart - that's still `eval.kind`'s job. Hardcoded per call site
# (never a caller-supplied value): `llm_call()` always reports "chat", `tool_call()` always reports
# "execute_tool" - both are simply what those two SDK methods always are.
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"

# Tool-call attributes: real GenAI semconv (unlike the "request.kind" idea considered and rejected
# for `EVAL_KIND` below - the spec genuinely has nothing like that).
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_DESCRIPTION = "gen_ai.tool.description"
GEN_AI_TOOL_TYPE = "gen_ai.tool.type"  # no closed enum in this package; "function" is the conventional value
GEN_AI_TOOL_CALL_ID = "gen_ai.tool.call.id"
GEN_AI_TOOL_CALL_ARGUMENTS = "gen_ai.tool.call.arguments"
GEN_AI_TOOL_CALL_RESULT = "gen_ai.tool.call.result"

# Agent-identity attributes: also real GenAI semconv, set once on a turn's own root span.
GEN_AI_AGENT_NAME = "gen_ai.agent.name"
GEN_AI_AGENT_ID = "gen_ai.agent.id"
GEN_AI_AGENT_DESCRIPTION = "gen_ai.agent.description"

# Workflow-identity: also real GenAI semconv, also set once on a turn's own root span - but unlike
# `gen_ai.agent.*` above, only when the caller actually orchestrates a multi-step workflow within
# one turn (reasoning_agent.py's classify->plan->solve->verify pipeline; classifier_router_agent.py's
# real LangGraph `StateGraph`). Pairs with `GEN_AI_OPERATION_NAME = "invoke_workflow"` on that same
# root span. Does NOT replace `EVAL_KIND`: this names the workflow as a whole (one value for the
# entire turn, identical across every call within it), not which step within it a given call is -
# the same reason `GEN_AI_OPERATION_NAME` alone can't either. Never set unprompted (e.g. not for
# chatbot.py, whose turn is a single call, not a workflow).
GEN_AI_WORKFLOW_NAME = "gen_ai.workflow.name"

EVAL_COST = "eval.cost"  # not part of GenAI semconv (it has no cost attribute) - this platform's own addition
EVAL_ERROR = "eval.error"  # ditto - the error message a failed tool call reported (also in the span status)
# the call's role in its turn (e.g. "classify"/"plan"/"solve"/"verify") - GenAI semconv has no such
# attribute (`gen_ai.operation.name` is a closed enum of API operation types like "chat", not an
# agent's own task labels - every call here would be "chat" alike), so this stays in our own `eval.`
# namespace rather than a fabricated `gen_ai.*` name implying spec compliance that doesn't exist.
EVAL_KIND = "eval.kind"


def setup_tracing(otlp_endpoint: str | None, *, service_name: str = "agent") -> TracerProvider | None:
    """This process's own tracer provider for the SDK's spans, or `None` - a graceful no-op, the
    same "unset = off" convention the platform's own backend tracer setup uses - when
    `otlp_endpoint` is unset. Never raises: construction doesn't contact the endpoint at all, and a
    later export failure is the SDK's own `BatchSpanProcessor`'s problem (it logs and drops,
    doesn't raise), not this function's."""
    if not otlp_endpoint:
        return None
    try:
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        # A short export deadline: this is best-effort telemetry, never something an agent's own
        # response path - or a `close()` call flushing on shutdown - should block noticeably on.
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True, timeout=2)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        return provider
    except Exception:
        log.warning("OTel tracer setup failed; this agent's spans are disabled", exc_info=True)
        return None


# Indicative price-per-1k-token figures for a handful of well-known cloud models, duplicated from
# (and must be kept in sync with) `backend/app/data/model_pricing.yaml` - the SDK is a standalone
# package with no path back to the backend's own file. Unpriced (including every local/self-hosted
# model) -> `compute_cost()` returns None, never a fabricated figure, exactly like the backend's.
_PRICES: dict[str, dict[str, float]] = {
    "gpt-4o": {"input_per_1k": 0.0025, "output_per_1k": 0.01},
    "gpt-4o-mini": {"input_per_1k": 0.00015, "output_per_1k": 0.0006},
    "o3-mini": {"input_per_1k": 0.0011, "output_per_1k": 0.0044},
    "claude-3-5-haiku": {"input_per_1k": 0.0008, "output_per_1k": 0.004},
    "claude-sonnet": {"input_per_1k": 0.003, "output_per_1k": 0.015},
}


def compute_cost(model: str | None, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
    """USD cost for one call, or `None` - never fabricated as 0 - when the model has no price-list
    entry or either token count is missing. Mirrors `backend/app/core/cost.py`'s `compute_cost()`:
    exact match first, then the longest price-list key the model id starts with (a provider often
    reports a dated snapshot, e.g. "gpt-4o-2024-08-06", for a priced family, "gpt-4o")."""
    if not model or prompt_tokens is None or completion_tokens is None:
        return None
    entry = _PRICES.get(model)
    if entry is None:
        candidates = [key for key in _PRICES if model.startswith(key)]
        if candidates:
            entry = _PRICES[max(candidates, key=len)]
    if entry is None:
        return None
    return (prompt_tokens / 1000.0) * entry["input_per_1k"] + (completion_tokens / 1000.0) * entry["output_per_1k"]
