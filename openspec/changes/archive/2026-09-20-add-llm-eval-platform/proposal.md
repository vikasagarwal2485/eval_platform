# Proposal

## Why

Choosing between locally hosted LLMs on Ollama is currently done by eyeballing a few chat sessions. There is no repeatable way to say "model A is more accurate at classification, model B reasons better, model C is 2x faster". A local evaluation platform makes that comparison objective, repeatable, and visible in one place, so a user can pick the right model for a task and see the accuracy/speed trade-off on their own hardware.

## What Changes

- Introduce a new web application (backend API + browser UI) that connects to a local Ollama server.
- Discover the models installed on Ollama and let the user select one or more of them for comparison.
- Let the user submit evaluation inputs in three categories: **classification**, **reasoning**, and **text generation**, either as ad-hoc prompts typed in the UI or as reusable test suites (with optional expected answers).
- Execute every selected model against every test case, capturing the raw output and Ollama's timing/token metrics.
- Score results: automatic correctness scoring for classification and reasoning (against expected answers), and rubric-based LLM-as-judge scoring for generated text and reasoning quality.
- Measure performance per model: time to first token, tokens/second, total latency, model load time, and token counts.
- Present a comparison dashboard: leaderboard, per-category scores, performance charts, side-by-side outputs, and per-case drill-down.
- Persist runs so results can be revisited, compared over time, and exported.

Non-goals (initial version): cloud/hosted model providers, fine-tuning or training, multi-user auth or remote deployment, GPU/CPU hardware telemetry beyond what Ollama reports, and distributed execution across machines.

## Capabilities

### New Capabilities

- `model-discovery`: List models installed on the local Ollama server (with size, parameters, quantization, capabilities) and report server connectivity/health.
- `test-suites`: Define, store, and import/export categorized test cases (classification, reasoning, generation) with optional expected answers, labels, and rubrics; ship with a small built-in starter suite; support one-off ad-hoc prompts.
- `evaluation-runs`: Orchestrate a run of selected models over selected test cases with configurable parameters (temperature, seed, repeats, context size), sequential execution, live progress, cancellation, and reproducible run records.
- `response-scoring`: Score model outputs per category (label match for classification, final-answer match for reasoning, rubric-based judge scoring for generation and reasoning quality) and compute per-category and weighted composite scores.
- `performance-metrics`: Capture and aggregate latency, time-to-first-token, tokens/second, load time, token counts, and memory footprint per model, separating cold-start from warm measurements.
- `results-dashboard`: Web UI for model selection, prompt entry, launching runs, and viewing/comparing results (leaderboard, charts, side-by-side outputs, run history, export).

### Modified Capabilities

<!-- None. The project has no existing specs. -->

## Impact

- **New code**: greenfield application in this repository (backend service, frontend SPA, SQLite persistence, built-in starter test suite).
- **External dependency**: a running Ollama server (default `http://localhost:11434`), used via its REST API (`/api/tags`, `/api/show`, `/api/chat`, `/api/ps`).
- **Runtime constraints**: local hardware limits how many models can be resident at once; evaluation is therefore sequential and model swapping cost (load time) is measured, not hidden.
- **Data**: runs, results, and scores stored locally in SQLite; no data leaves the machine.
- **Environment today**: only `qwen3:8b` is installed, so the platform must work with a single model (results view, absolute scores) and light up comparison features as more models are pulled.
