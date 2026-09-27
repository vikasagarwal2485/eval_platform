# Reference agents

Two small, runnable agents that demonstrate the live-agent-evaluation loop end to end: they run outside the eval
platform, stream every interaction into it over the [agent SDK](eval_agent_sdk/__init__.py), and get evaluated by
a model that never produced their answers.

- **`chatbot.py`** - a REPL chatbot over one local Ollama model. Each exchange is one turn with one LLM span.
- **`reasoning_agent.py`** - answers a problem through three LLM calls per turn (plan, solve, verify), so one turn
  has multiple spans. `--suite` replays a suite file's reasoning cases and sends each one's expected answer as the
  turn's reference, so the platform's deterministic correctness check runs alongside the evaluator's score.

Both need only `httpx` (see [`eval_agent_sdk`](eval_agent_sdk/__init__.py)) - no platform backend dependency.

## Demonstration setup: agent and evaluator on different models

The point of this capability is that an agent is never evaluated by the model that answered. Use two different
local models (or register an enterprise model as the evaluator via `/api/providers`, once `add-enterprise-model
-providers` is in place).

1. **Start the platform** (from the repo root): `make run` (serves on `http://localhost:8000`), with Ollama
   running and at least two models pulled, e.g. `qwen3:8b` (the agent) and `gemma3:4b` (the evaluator).

2. **Register the agent**, declaring the model it uses, and note the ingest token shown once:

   ```bash
   curl -s -X POST http://localhost:8000/api/agents \
     -H 'Content-Type: application/json' \
     -d '{"name": "demo-chatbot", "kind": "chatbot", "declared_model": "qwen3:8b"}'
   # => {"id": 1, "token": "<TOKEN>", ...}
   ```

3. **Configure a different model as its evaluator** (saving an evaluator equal to the declared model is rejected -
   see spec `agent-registry`):

   ```bash
   curl -s -X PATCH http://localhost:8000/api/agents/1 \
     -H 'Content-Type: application/json' \
     -d '{"eval_config": {"evaluators": ["gemma3:4b"], "quiet_period_s": 5}}'
   ```

4. **Run the chatbot** against the platform:

   ```bash
   python -m agents.chatbot --model qwen3:8b --platform-url http://localhost:8000 --token <TOKEN>
   ```

   Or the reasoning agent, once on a single problem and once replaying a suite's reasoning cases:

   ```bash
   python -m agents.reasoning_agent --model qwen3:8b --platform-url http://localhost:8000 --token <TOKEN> \
     --problem "A train travels 60 miles in 40 minutes. What is its speed in mph?"

   python -m agents.reasoning_agent --model qwen3:8b --platform-url http://localhost:8000 --token <TOKEN> \
     --suite backend/app/data/starter_suite.yaml
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
