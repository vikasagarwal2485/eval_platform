# Agent LLM Gateway

A shared [LiteLLM Proxy](https://docs.litellm.ai/docs/simple_proxy) that routes an agent process's
LLM calls to a provider deployment by a task-scoped model group name (`<agent-slug>__<task_type>`,
e.g. `reasoning-agent__reasoning`), instead of each agent holding its own direct, hardcoded
connection to a single provider. See `openspec/changes/add-litellm-gateway-infra/` (proposal,
specs, design) for why this exists and what it's required to do.

## Prerequisites

- Python 3.11+ and `pip`.
- A **PostgreSQL database** for the proxy's virtual-key store. Virtual keys (one per agent
  process, scoped to that agent's own model groups - see "Virtual keys" below) require a real,
  connected Postgres database; the proxy's `/key/generate` endpoint returns an error without one.
  This was not anticipated in the original design (`design.md`'s non-goals only called out HA/
  scaling as out of scope) - it is a hard dependency of LiteLLM's virtual-key feature itself, not
  an optional extra. For local/dev:
  ```bash
  docker run -d --name litellm-gateway-pg \
    -e POSTGRES_PASSWORD=litellm -e POSTGRES_DB=litellm \
    -p 5540:5432 postgres:16-alpine
  ```
- A local Ollama instance for the dev-default model groups (`ollama_chat/qwen3:8b`,
  `ollama_chat/gemma4:e4b`), or real provider credentials if you've swapped `config.yaml`'s
  deployments for a cloud provider (see the comments in that file), or if any agent's
  `declared_models` reference one (see "Provider credentials" below - this is a separate,
  commonly-missed requirement from the platform's own provider registration).

## Install

```bash
cd gateway
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt   # pinned litellm[proxy] - see requirements.txt's comment
```

Verify: `.venv/bin/litellm --version` should print the pinned version with no errors.

### One-time: generate the Prisma client

The proxy's virtual-key store is backed by Prisma. Its Python client has native binaries that
must be generated once per environment before first start - the proxy installs `prisma` as a
dependency but does **not** run this step for you, and will crash on startup with
`Unable to find Prisma binaries. Please run 'prisma generate' first.` if skipped:

```bash
export DATABASE_URL="postgresql://postgres:litellm@localhost:5540/litellm"
export PATH="$PWD/.venv/bin:$PATH"   # so prisma's generator subprocess finds prisma-client-py
prisma generate --schema .venv/lib/python3.11/site-packages/litellm/proxy/schema.prisma
```

## Run (supervised, not an ad hoc background process)

```bash
export LITELLM_MASTER_KEY="<operator-only secret, never shared with an agent process>"
export DATABASE_URL="postgresql://postgres:litellm@localhost:5540/litellm"
export STORE_MODEL_IN_DB=True   # required for dynamic, registry-driven model groups - see below
.venv/bin/litellm --config config.yaml --port 4000
```

Run this under a process supervisor (systemd, launchd, a container orchestrator, or at minimum
`nohup ... & disown` with a documented PID file) in any setting an agent actually depends on it -
never as a bare foreground process someone's terminal session can kill by accident. First start
against a fresh database applies ~195 bundled schema migrations automatically; subsequent starts
are fast (a few seconds).

**Stop**: send the process `SIGTERM` (or stop it the way your supervisor stops services) and
confirm `scripts/health_check.sh` starts failing.

## Health check

```bash
scripts/health_check.sh                    # defaults to http://localhost:4000
scripts/health_check.sh http://other:4000   # or pass a different base URL
```
Exits 0 and prints `healthy: ...` when the proxy's `/health/liveliness` endpoint returns 200;
exits 1 and prints `unhealthy: ...` otherwise.

## Model groups

`config.yaml` defines one Router model group per `(agent, task type)`, named
`<agent-slug>__<task_type>`. The dev default ships only `reasoning-agent__reasoning` and
`reasoning-agent__generation`, pointed at two different local Ollama models so the two groups are
observably distinct without needing any provider credential. Swap a deployment for a real cloud
provider by changing its `model:` to `<provider>/<model>` and its `api_key:` to
`os.environ/<VAR>` - see the commented examples in `config.yaml`. **Never put a literal provider
key in this file.**

A request addressed to a group name that isn't configured is rejected (HTTP 403,
`key_model_access_denied` for a scoped key missing it, or a routing error for an unscoped
request) rather than silently routed elsewhere. Two agents' same-named task-type groups (e.g. two
different agents each with their own `reasoning` group) are fully isolated from each other -
model group names are matched exactly, so one agent's traffic can never reach a deployment
configured under a different agent's group.

## Provider credentials

A group's `api_key` - whether hand-written in `config.yaml` or pushed dynamically by the platform
via `add-gateway-model-sync` (see below) - is almost always an `os.environ/<VAR>` *reference*, not
a literal key. The gateway process resolves that reference **itself**, out of **its own**
environment, every time it's needed - never from the backend's environment, never from your shell
unless that shell is the one that actually launched `litellm`.

This trips people up in a specific, reproducible way: the platform's own `/api/providers`
registration (`key_env: "AZURE_OPENAI_API_KEY"`, say) only proves the **backend** process can see
that variable - it says nothing about the **gateway** process, which is separate and does not
inherit the backend's environment. Syncing a declared model that references that provider
(`add-gateway-model-sync`) succeeds either way, since sync only writes the reference string - the
failure only surfaces later, at **call time**, as something like:

```
litellm.InternalServerError: ... Missing credentials. Please pass one of `api_key`, ... or the
`AZURE_OPENAI_API_KEY` ... environment variable. LiteLLM: model group '<group>' failed ...
```

Fix: export the same key value the backend already uses for that provider, in the shell that
launches the gateway, then restart it - **environment variables set in another terminal, or after
the gateway process has already started, do not reach it**:

```bash
export AZURE_OPENAI_API_KEY="<the same value the platform's /api/providers registration uses>"
export LITELLM_MASTER_KEY="..."
export DATABASE_URL="postgresql://postgres:litellm@localhost:5540/litellm"
export STORE_MODEL_IN_DB=True
.venv/bin/litellm --config config.yaml --port 4000
```

Nothing needs re-registering or re-syncing on the platform side for this - `declared_models`
already pushed the correct `os.environ/<VAR>` reference; the gateway just needs that variable
present in its own environment to resolve it. One variable per provider `key_env` the gateway
will ever be asked to use (match whatever name is registered on the platform's Providers page),
set once at gateway startup, covers every agent's declared model or evaluator from that provider.

## Dynamic model groups (registry-driven, `add-gateway-model-sync`)

With `STORE_MODEL_IN_DB=True`, model groups can be created, updated and removed at runtime - no
restart, no editing `config.yaml` - through `/model/new`, `/model/update` and `/model/delete`.
This is how the platform keeps an agent's gateway model groups in sync with its `declared_models`
instead of requiring them to be hand-authored here. Static `config.yaml` entries and dynamic,
database-backed ones coexist without conflict; this file's own `reasoning-agent__reasoning`/
`reasoning-agent__generation` entries remain as the dev-default baseline.

```bash
curl -s -X POST http://localhost:4000/model/new \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"model_name": "my-agent__reasoning",
       "litellm_params": {"model": "ollama_chat/qwen3:8b", "api_base": "http://localhost:11434", "temperature": 0.2}}'
```
A credential given as `"api_key": "os.environ/<VAR>"` is resolved and stored encrypted at rest by
the gateway - it is never echoed back in the `/model/new`/`/model/update` response, and the
caller never needs to hold the literal value (verified directly against this gateway).

**Credential for the backend's own sync calls**: do not configure the backend with the literal
`LITELLM_MASTER_KEY`. Mint it a dedicated, independently-rotatable `proxy_admin`-role credential
instead:

```bash
curl -s -X POST http://localhost:4000/user/new \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"user_role": "proxy_admin", "user_alias": "backend-gateway-sync"}'
# => the response's "key" can call /model/new, /model/update and /model/delete, exactly like the
#    master key for this purpose, but is a separate, revocable credential (verified directly: a
#    plain virtual key without this role gets 403 "Your role=internal_user" on /model/new).
```
This is `proxy_admin`-scoped, not a narrower "model management only" role - LiteLLM did not expose
a finer-grained permission for this in the version tested. Store and rotate it with the same
discipline as the virtual keys below.

**Wiring it into the backend**: set these two on the **backend** process (not here - they're read
by `app/config.py`'s `load_settings()`), so `PATCH`/`POST /api/agents` actually calls this gateway
instead of silently reporting `gateway_sync: {"status": "skipped"}`:

```bash
export EVAL_GATEWAY_URL="http://localhost:4000"        # this gateway's address
export EVAL_GATEWAY_ADMIN_KEY="<the proxy_admin key minted above>"
make run   # from the repo root
```

## Virtual keys

Agents never hold a provider credential or the `master_key` - only a virtual key scoped to their
own model groups, minted with the master key:

```bash
curl -s http://localhost:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"models": ["reasoning-agent__reasoning", "reasoning-agent__generation"], "key_alias": "reasoning-agent"}'
```
The response's `"key"` field is the agent's credential; it never appears in any gateway log (grep
your own deployment's logs to confirm, as this repo's own verification did - see tasks.md 4.1).
A key scoped to one agent's groups is rejected if presented against a group it wasn't minted for.

**Storage and rotation**: store the minted key the same way the platform's own agent ingest token
is handled (`agent-registry` spec: hashed at rest, a short prefix for display, never logged or
exported) - this repo does not yet have a place in `backend/` to store a gateway virtual key
(that's out of scope for this phase; see `add-litellm-gateway-infra`'s design.md). Until that
exists, treat the key as you would any other long-lived credential: pass it to the agent process
only via its own environment, never commit it, and re-mint (`/key/generate` again) and discard the
old value to rotate - LiteLLM does not currently expose an in-place rotate-this-key endpoint, so
rotation is "mint a new key, retire the old one," matching this file's own test key hygiene.
**LiteLLM enforces globally unique `key_alias` values**, so a bare second `/key/generate` for the
same alias is rejected with `400 Key with alias '...' already exists` - delete the old key by
alias first (safe even if nothing is minted under it yet):

```bash
curl -s http://localhost:4000/key/delete \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"key_aliases": ["reasoning-agent"]}'
```
(the backend's own automated minting, `backend/app/core/gateway_sync.py`'s `mint_virtual_key()`,
does this `/key/delete` itself before every `/key/generate` for a playground-eligible agent - found
live when a re-mint for an already-minted agent 400'd with exactly this error.)

## Fallback groups (`add-declared-model-fallback`)

A declared model's optional `fallback` is synced to its own gateway group -
`<agent-slug>__<task_type>__fallback` - alongside the primary `<agent-slug>__<task_type>` group,
exactly the same way (`/model/new`/`/model/update`/`/model/delete`, created on demand, removed when
the fallback is cleared or the task type itself is removed).

**A configured fallback group does nothing unless the caller's own request names it.** This was
verified directly against this gateway while researching the feature: passing
`"fallbacks": ["<fallback-group-name>"]` on the individual completion request causes LiteLLM to
retry against that group when the primary is unreachable, and the response's
`x-litellm-model-group` header (or, for this repo's own agents, `_concrete_model`'s resolution of
`x-litellm-model-name`) identifies which group actually answered. Configuring a fallback
gateway-wide instead, via `POST /config/update`'s `litellm_settings.fallbacks`, was also tested
live and found **unreliable** - the endpoint reports success, but a subsequent request that does
not itself pass `fallbacks` still fails with no fallback attempted. There is no gateway-wide
default to rely on; every caller that wants a fallback must name it on every request.

**A caller through the `litellm` Python SDK's client-side `completion()` (as opposed to a direct
REST call to this gateway's own `/chat/completions`) needs one more thing**, also found live while
implementing this: if your call already prefixes its primary `model` with `openai/<group>` to make
an arbitrary `api_base` work (see "Model groups" above), the `fallbacks` entry needs that same
`openai/` prefix too - the SDK's own client-side fallback retry calls `completion()` again with
whatever string you gave it, verbatim, and an unprefixed group name fails there with `LLM Provider
NOT provided`, the identical error an unprefixed primary model gets. `reasoning_agent.py`'s
`call_llm` does this correctly (`fallbacks=[f"openai/{fallback_group}"]`) - copy that, not a bare
group name, if you're writing a new agent against this gateway.

`reasoning_agent.py`'s `--reasoning-fallback-group`/`--generation-fallback-group` flags are the
reference implementation of this - unset by default (no fallback passed), matching the
`--reasoning-model-group`/`--generation-model-group` flags' own temporary, explicit pattern (see
that module's docstring).

A virtual key scoped only to an agent's primary groups will be rejected if the agent's own code
ever names a fallback group that key wasn't minted for - remember to add the fallback group name to
the key's `"models"` allow-list (see "Virtual keys" above) alongside the primary when one is
configured.

## What's still out of scope

- No scheduled reconciliation if a registry-to-gateway sync fails - see
  `add-gateway-model-sync`'s design.md; retrying happens the next time an agent's settings are
  saved, not on a timer.
