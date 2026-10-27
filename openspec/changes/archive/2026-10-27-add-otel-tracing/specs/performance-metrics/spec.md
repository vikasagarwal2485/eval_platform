# Spec Delta

## MODIFIED Requirements

### Requirement: Per-request metrics
The system SHALL record, for every request: total latency, time to first token, time to first answer token (after any thinking output), model load duration, prompt token count, output token count, thinking token count when available, prompt evaluation duration, generation duration, and generation throughput in tokens per second. For enterprise models, token counts SHALL come from the provider's reported usage and timings from client-side measurement, and the source of each figure SHALL be recorded. When an enterprise provider reports that some of a request's prompt tokens were served from its own prompt cache, the system SHALL record that cached-token count alongside the prompt token count rather than discarding it. The system SHALL also compute and record a cost figure for the request from its token counts and a maintained price list, when the model has a known price; an unpriced model records no cost rather than a fabricated one.

#### Scenario: Metrics recorded
- **WHEN** a request completes successfully
- **THEN** all available metrics are stored with the result, sourced from Ollama-reported counters where provided and from wall-clock timing otherwise

#### Scenario: Throughput calculation
- **WHEN** Ollama reports an output token count and a generation duration
- **THEN** tokens per second is output tokens divided by generation duration in seconds

#### Scenario: Metric unavailable
- **WHEN** a metric cannot be obtained for a request (for example the request failed before the first token)
- **THEN** the metric is stored as absent, never as zero, and is excluded from aggregates

#### Scenario: Enterprise request metrics
- **WHEN** an enterprise request completes
- **THEN** latency and time to first token are measured by the client, prompt and output token counts come from the provider's usage report, and load duration and evaluation durations are stored as absent

#### Scenario: Throughput for a cloud request
- **WHEN** an enterprise request reports an output token count
- **THEN** tokens per second is the output tokens divided by the time between the first output token and the end of the stream, and is marked as client-measured

#### Scenario: Cached prompt tokens recorded
- **WHEN** an enterprise request's usage report includes a cached-prompt-token count
- **THEN** the result stores that count alongside the prompt token count

#### Scenario: No cache information reported
- **WHEN** an enterprise provider's usage report does not include a cached-token count, or the request used a local Ollama model
- **THEN** the cached-token count is stored as absent, never as zero

#### Scenario: Cost is computed for a priced model
- **WHEN** a request completes for a model with a configured price-per-token entry
- **THEN** its cost is computed from its recorded prompt and output token counts and stored with the result

#### Scenario: No cost is fabricated for an unpriced model
- **WHEN** a request completes for a model with no configured price-list entry
- **THEN** no cost figure is recorded for that request - it is absent, not zero
