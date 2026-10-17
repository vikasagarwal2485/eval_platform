# Reference agents

Two small, runnable agents that demonstrate the live-agent-evaluation loop end to end: they run outside the eval
platform, stream every interaction into it over the [agent SDK](eval_agent_sdk/__init__.py), and get evaluated by
a model that never produced their answers.

- **`chatbot.py`** - a REPL chatbot over one local Ollama model. Each exchange is one turn with one LLM span.
- **`reasoning_agent.py`** - answers a problem through three LLM calls per turn (plan, solve, verify), so one turn
  has multiple spans, potentially from different models. `--suite` replays a suite file's reasoning cases and
  sends each one's expected answer as the turn's reference, so the platform's deterministic correctness check
  runs alongside the evaluator's score.

`chatbot.py` needs only `httpx` (see [`eval_agent_sdk`](eval_agent_sdk/__init__.py)) - no platform backend
dependency. `reasoning_agent.py` also needs `litellm` (its LLM calls go through the shared gateway - see
*Task-routed calls* below) and, for `--suite <file>.yaml`, `pyyaml` (a `.json` suite needs nothing extra). See
[`requirements.txt`](requirements.txt).

### Task-routed calls (`reasoning_agent.py`)

By default, `reasoning_agent.py`'s plan and verify calls route through the shared LLM gateway
([`gateway/`](../gateway/), `openspec/changes/add-litellm-gateway-infra`) to the `reasoning-agent__reasoning`
model group, and its solve call to `reasoning-agent__generation` - each group can be configured with a different
model, so one turn's three calls aren't necessarily all answered by the same model. This needs the gateway
running (`gateway/README.md`) and a virtual key scoped to those two groups:

```bash
agents/.venv/bin/python -m agents.reasoning_agent --platform-url http://localhost:8000 --token <TOKEN> \
  --gateway-key <virtual-key-from-gateway/README.md> --problem "..."
```
`--gateway-url` defaults to `http://localhost:4000` (the gateway's local dev default) and rarely needs setting.

**If you registered the agent under a name other than `"reasoning-agent"`**, its `declared_models`-synced
gateway groups (`add-gateway-model-sync`) are named `<your-agent-slug>__reasoning`/
`<your-agent-slug>__generation`, not the hardcoded defaults above - the agent does not yet discover its own
group names at runtime (a known, temporary gap - see the module's own docstring), so pass them explicitly:

```bash
agents/.venv/bin/python -m agents.reasoning_agent --platform-url http://localhost:8000 --token <TOKEN> \
  --gateway-key <virtual-key-scoped-to-your-agent's-groups> \
  --reasoning-model-group my-reasoner__reasoning --generation-model-group my-reasoner__generation \
  --problem "..."
```

For simple local testing **without** the gateway, pass `--model` with a literal LiteLLM model string (e.g.
`ollama_chat/qwen3:8b`) - this overrides all three calls to that one model and skips the gateway entirely, the
same single-model behavior the agent had before task-routing:

```bash
agents/.venv/bin/python -m agents.reasoning_agent --platform-url http://localhost:8000 --token <TOKEN> \
  --model ollama_chat/qwen3:8b --problem "..."
```

## Setup

These agents are meant to run **anywhere** - not necessarily on the same machine or in the same Python
environment as the platform itself - so they get their own small venv, separate from `backend/.venv`:

```bash
make agents-setup   # from the repo root: creates agents/.venv and installs requirements.txt
```

Run either agent from the **repo root** with that venv's interpreter, e.g.
`agents/.venv/bin/python -m agents.chatbot --help`. If you're already inside `backend/.venv` (it depends on
`httpx` and `pyyaml` too), that works as well - a separate venv is a convenience, not a requirement.

## Demonstration setup: agent and evaluator on different models

The point of this capability is that an agent is never evaluated by the model that answered. Use two different
local models, or register an enterprise model as the evaluator via `/api/providers` (see the main README's
*Enterprise model providers* section).

1. **Start the platform** (from the repo root): `make run` (serves on `http://localhost:8000`), with Ollama
   running and at least two models pulled, e.g. `qwen3:8b` (the agent) and `gemma3:4b` (the evaluator).

2. **Register the agent**, declaring the model(s) it uses, and note the ingest token shown once. `declared_models`
   is a map keyed by task type - `chatbot.py` has one undifferentiated task, so it uses the conventional
   `"default"` key; a task-routed `reasoning_agent.py` would declare `{"reasoning": "...", "generation": "..."}`
   instead (see *Task-routed calls* above). A value can be a plain model-reference string, or an object carrying
   generation-parameter overrides - for example `{"model": "qwen3:8b", "params": {"temperature": 0.2}}`:

   ```bash
   curl -s -X POST http://localhost:8000/api/agents \
     -H 'Content-Type: application/json' \
     -d '{"name": "demo-chatbot", "kind": "chatbot", "declared_models": {"default": "qwen3:8b"}}'
   # => {"id": 1, "token": "<TOKEN>", ...}
   ```

   If the gateway is running with `STORE_MODEL_IN_DB=True` and the backend has a gateway admin credential
   configured (`gateway/README.md`), registering or updating `declared_models` also creates or updates the
   matching gateway model group automatically - `gateway/config.yaml` is no longer the only way a per-agent
   group gets configured. The response's `gateway_sync` field reports the outcome per task type; a failure
   there never blocks the registration itself (see `openspec/changes/add-gateway-model-sync`).

3. **Configure a different model as its evaluator** (saving an evaluator matching any declared model is rejected -
   see spec `agent-registry`):

   ```bash
   curl -s -X PATCH http://localhost:8000/api/agents/1 \
     -H 'Content-Type: application/json' \
     -d '{"eval_config": {"evaluators": ["gemma3:4b"], "quiet_period_s": 5}}'
   ```

4. **Run the chatbot** against the platform (from the repo root, using the venv from *Setup* above):

   ```bash
   agents/.venv/bin/python -m agents.chatbot --model qwen3:8b --platform-url http://localhost:8000 --token <TOKEN>
   ```

   Or the reasoning agent, once on a single problem and once replaying a suite's reasoning cases - here using
   `--model` to skip the gateway and keep this demo to one model, matching the setup above (see *Task-routed
   calls* above for running it against the gateway's two separate model groups instead):

   ```bash
   agents/.venv/bin/python -m agents.reasoning_agent --model ollama_chat/qwen3:8b --platform-url http://localhost:8000 \
     --token <TOKEN> --problem "A train travels 60 miles in 40 minutes. What is its speed in mph?"

   agents/.venv/bin/python -m agents.reasoning_agent --model ollama_chat/qwen3:8b --platform-url http://localhost:8000 \
     --token <TOKEN> --suite backend/app/data/starter_suite.yaml
   ```

5. **Watch it get evaluated.** After the configured quiet period, open the agent in the UI (Agents -> demo-chatbot)
   or poll its turns:

   ```bash
   curl -s http://localhost:8000/api/agents/1/turns | python3 -m json.tool
   ```

   Each turn's evaluation shows a score from `gemma3:4b`, never a self-judged one - `qwen3:8b` (the agent's own
   model) is never eligible to evaluate its own turns, even if it were mistakenly added to the evaluator list
   (that save is rejected up front).

`tests/test_reference_agents.py` and `tests/test_reference_agents_demo.py` in the backend test suite exercise
this same shape - the exact events the agents emit, and the full ingest-to-evaluation path - without needing a
live Ollama or platform process.
