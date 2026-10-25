# Spec Delta

## MODIFIED Requirements

### Requirement: Run history and comparison across runs
The web UI SHALL list past runs and let the user open one or select two runs to compare (for
example the same model before and after a quantization or settings change). For a model present in
both runs, the comparison SHALL explain plausible reasons for a latency or tokens-per-second
difference when the platform can identify one (for example a cold-start share difference, a
changed model digest, or a different attached skill or generation setting between the two runs).

#### Scenario: Compare two runs
- **WHEN** the user selects two runs
- **THEN** the UI shows score and performance deltas for models and cases present in both

#### Scenario: Cached-token share differs between runs
- **WHEN** the user compares two runs for the same model and one run's measured cached-prompt-token
  share differs meaningfully from the other's
- **THEN** the comparison names that difference as a plausible reason the latency or
  tokens-per-second changed, alongside any other reason already shown for that model
