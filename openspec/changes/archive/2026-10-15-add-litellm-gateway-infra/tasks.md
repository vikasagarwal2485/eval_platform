# Tasks

## 1. Gateway process

- [x] 1.1 Add a `gateway/` directory with a pinned `litellm[proxy]` install procedure (document
      the exact version pin, per the companion proposal doc's dependency-risk note) and verify
      `litellm --version` runs in a clean environment following only the documented steps
- [x] 1.2 Document the supervised run procedure (not an ad hoc background process) for local/dev
      - start, stop, health check - in `gateway/README.md`, and verify by following it from a
      cold shell
- [x] 1.3 Add a health-check script or documented `curl` command against the proxy's health
      endpoint and verify it reports healthy once the process is up

## 2. Model groups and credentials

- [x] 2.1 Write `gateway/config.yaml` with the two `reasoning-agent__reasoning` and
      `reasoning-agent__generation` model groups, each `api_key` sourced via
      `os.environ/<VAR>` (never a literal key), and verify the proxy starts cleanly with this
      config and `openspec show agent-llm-gateway --type spec` requirements are each
      demonstrably met (one scenario below per requirement)
- [x] 2.2 Set `general_settings.master_key` from an environment variable; verify an unauthenticated
      request to the proxy is rejected
- [x] 2.3 Mint one virtual key scoped to `reasoning-agent__*` and verify a request using it
      succeeds for both configured groups and a request using it against an unrelated group name
      (none configured yet, but simulate with a second dummy group) is rejected

## 3. Verify against the spec

- [x] 3.1 Verify "Task-scoped model groups": a request addressed to `reasoning-agent__reasoning`
      reaches the configured deployment; a request addressed to an unconfigured group name is
      rejected with an identifying error
- [x] 3.2 Verify "Gateway-held provider credentials": inspect the reasoning agent's virtual key
      and confirm it contains no provider credential; confirm the request still reaches the
      provider
- [x] 3.3 Verify "No silent deployment substitution": point a model group's deployment at an
      unreachable `api_base` and confirm the proxy returns an error rather than silently routing
      elsewhere
- [x] 3.4 Verify "Model groups are scoped per agent": configure a second dummy agent's `reasoning`
      group pointed at a different deployment and confirm a request to each group only ever
      reaches its own deployment

## 4. Secrets hygiene

- [x] 4.1 Confirm no provider key, virtual key, or master key appears in the gateway's own logs
      or any committed file; verify by grepping startup/request logs after a round of test
      traffic and checking `gateway/config.yaml` contains only `os.environ/...` references
- [x] 4.2 Document the virtual key's storage and rotation procedure in `gateway/README.md`,
      mirroring the ingest token discipline already documented for agents (hashed/rotatable,
      never logged) even though this key is managed by the gateway, not the platform's own DB
