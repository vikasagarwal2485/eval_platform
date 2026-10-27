# Observability stack

An OpenTelemetry Collector, Grafana Tempo, and Grafana - self-contained and separate from the main
backend's own deploy, the same way [`gateway/`](../gateway/) is a self-contained LiteLLM proxy
independent of the backend. See `openspec/changes/add-otel-tracing/` (proposal, specs, design) for
why this exists.

**Nothing else depends on this stack being up.** The Runner, the benchmark results, agent ingest,
and evaluation (sampling, judging, the attention dashboard) all work normally whether or not this
is running. Only the platform's own trace-tree view (and, if you want it, Grafana itself) needs it.

```
Backend (Runner spans) --+
                          +--> otel-collector :4317/:4318 (OTLP) --> tempo :4317 (OTLP) --> tempo :3200 (query API)
Agents (OTel SDK spans) --+                                                                      ^
                                                                                                    |
                                                        Grafana :3000 (Tempo provisioned as its data source)
                                                        Backend's own `/api/traces/{trace_id}` proxy (add-otel-tracing)
```

## Prerequisites

- Docker and `docker compose` (v2).

## Run

```bash
cd observability
docker compose up -d
```

This starts all three services with no other part of the platform running. First start pulls the
three images (`otel/opentelemetry-collector-contrib`, `grafana/tempo`, `grafana/grafana`); Tempo
and the Collector come up within a few seconds, Grafana within about ten.

**Stop**: `docker compose down` (add `-v` to also drop Tempo's stored trace data, kept in the
`tempo-data` Docker volume otherwise).

## Health check

```bash
scripts/health_check.sh                                          # defaults below
scripts/health_check.sh http://other:13133 http://other:3200 http://other:3000
```
Checks the Collector's `health_check` extension, Tempo's `/ready`, and Grafana's `/api/health`;
exits 0 only if all three report healthy.

## Ports

| Service | Port | Purpose |
|---|---|---|
| otel-collector | 4317 | OTLP gRPC - what the backend's Runner and agents' OTel SDKs export spans to |
| otel-collector | 4318 | OTLP HTTP (alternative to 4317) |
| otel-collector | 13133 | `health_check` extension |
| tempo | 3200 | Tempo's own HTTP query API - what the backend's Tempo-query client (`add-otel-tracing` task 4.1) calls to fetch a trace by id |
| grafana | 3000 | Grafana's own UI, with Tempo already provisioned as its data source |

## Pointing the backend and agents at this stack

- **Backend** (the Runner's own spans): set `EVAL_OTEL_ENDPOINT` before starting it, e.g.
  `EVAL_OTEL_ENDPOINT=localhost:4317 .venv/bin/uvicorn app.main:app_factory --factory ...` from
  `backend/` - read once at process startup (`app/config.py`), so the backend must be (re)started
  after setting it, not just the env var exported in the same shell before it was already running.
  The backend also needs `EVAL_TEMPO_BASE_URL=http://localhost:3200` so its own
  `/api/traces/{trace_id}` proxy (not the browser) can query Tempo directly for the frontend's
  trace-tree view.
- **Agents** (the reference `chatbot.py`/`reasoning_agent.py`/`classifier_router_agent.py`, and any
  agent built on `eval_agent_sdk`): each has its own `--otel-endpoint` CLI flag, which **falls back
  to this same `EVAL_OTEL_ENDPOINT` env var** when the flag is omitted - set it once in a shell
  before launching an agent and it's picked up automatically, the same as the backend. A custom
  agent calling `AgentClient(...)` directly (not through one of these reference CLIs) must resolve
  this env var itself and pass the result as `otel_endpoint=` - the SDK's own constructor does not
  read the environment implicitly, by design (see `add-otel-tracing`'s design.md).

Point it at `http://localhost:4317` for a local setup matching this compose file, or wherever this
stack actually runs otherwise. Leaving it unset (both the flag and the env var) is a supported,
graceful no-op everywhere: spans simply aren't emitted, nothing fails.

## Grafana login

Default local/dev credentials: `admin` / `admin` (or the `GRAFANA_ADMIN_PASSWORD` environment
variable if set before `docker compose up`). Anonymous viewer access is also enabled by default for
local convenience (`GF_AUTH_ANONYMOUS_ENABLED`) - see "Production notes" below before relying on
either of these beyond your own machine.

## Viewing a trace

- **In the platform's own frontend**: open a benchmark result or agent turn that has a trace - its
  drill-down fetches and renders the span tree automatically via the backend's own proxy endpoint.
- **In Grafana**: Explore -> Tempo -> paste the `trace_id` (shown alongside the result/turn in the
  platform's own UI) -> the same trace, Grafana's own way.

## Production notes

This compose file is a local/dev default, not a hardened deployment:
- `GF_AUTH_ANONYMOUS_ENABLED=true` and the default admin password are both fine for a single
  developer's own machine, not for anything reachable by anyone else - disable anonymous access
  and set a real `GRAFANA_ADMIN_PASSWORD` before exposing this beyond `localhost`.
- The Collector's OTLP exporter to Tempo uses `tls.insecure: true` - this is same-Docker-network
  traffic in this compose file; add real TLS if the Collector and Tempo ever run on different
  hosts/networks.
- Tempo's storage backend here is local disk in a Docker volume (`storage.trace.backend: local` in
  `tempo.yaml`) with 48h retention - single-machine scale, matching this project's existing
  "computed over stored rows, no separate pre-aggregation cluster" stance elsewhere
  (`cross-model-judging`, `performance-metrics`). Swap it for S3/GCS and move Tempo to its
  microservices deployment mode if this ever needs to run beyond one machine or retain traces
  longer.
