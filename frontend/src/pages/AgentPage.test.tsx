import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FakeEventSource } from '../test/fakeEventSource';
import { jsonError, mockApi, renderApp } from '../test/utils';
import AgentPage from './AgentPage';

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
});
afterEach(() => {
  vi.unstubAllGlobals();
  FakeEventSource.instances = [];
});

const AGENT = {
  id: 1,
  name: 'demo-chatbot',
  kind: 'chatbot',
  declared_models: { default: 'author:1' },
  status: 'active',
  liveness: 'idle',
  token_prefix: 'abcd1234',
  eval_config: {
    evaluators: ['judge:1'],
    sample_rate: 1,
    quiet_period_s: 20,
    context_turns: 4,
    attention_threshold: 0.5,
    abandon_after_s: 600,
    retention_days: null,
  },
  rubric: null,
  provider_acks: [],
  last_seen_at: null,
  created_at: '2026-01-01T00:00:00Z',
  playground_eligible: false,
  flavor: null,
  playground_gateway_key_configured: false,
  handoff_agent_names: [],
};

const MODELS = [
  {
    name: 'author:1',
    digest: 'd1',
    size_bytes: 1,
    parameter_size: null,
    quantization: null,
    family: null,
    capabilities: [],
    thinking: false,
    source: 'local',
    provider: null,
    provider_kind: null,
    display_name: null,
    reasoning: false,
    available: true,
    unavailable_reason: null,
  },
  {
    name: 'judge:1',
    digest: 'd2',
    size_bytes: 1,
    parameter_size: null,
    quantization: null,
    family: null,
    capabilities: [],
    thinking: false,
    source: 'local',
    provider: null,
    provider_kind: null,
    display_name: null,
    reasoning: false,
    available: true,
    unavailable_reason: null,
  },
  {
    name: '@oa/gpt-4o',
    digest: '',
    size_bytes: null,
    parameter_size: null,
    quantization: null,
    family: null,
    capabilities: [],
    thinking: false,
    source: 'cloud',
    provider: 'oa',
    provider_kind: 'openai',
    display_name: 'GPT-4o',
    reasoning: false,
    available: true,
    unavailable_reason: null,
  },
];

const TURN = {
  id: 5,
  external_id: 't1',
  session_id: 's1',
  seq: 0,
  status: 'ok',
  input: 'hi there',
  output: 'hello!',
  reference: null,
  error: null,
  models: ['author:1'],
  models_unknown: false,
  truncated: false,
  latency_ms: 120,
  prompt_tokens: 5,
  completion_tokens: 3,
  started_at: '2026-01-01T00:00:00Z',
  ended_at: '2026-01-01T00:00:01Z',
  latest_evaluation: { status: 'done', value: 0.8 },
};

const TURN_DETAIL = {
  ...TURN,
  spans: [
    {
      id: 1,
      kind: 'llm',
      model: 'author:1',
      name: null,
      input: {},
      output: 'hello!',
      thinking: null,
      error: null,
      started_at: null,
      ended_at: null,
      latency_ms: 100,
      ttft_ms: null,
      prompt_tokens: 5,
      completion_tokens: 3,
    },
  ],
  evaluations: [
    {
      id: 9,
      attempt_no: 1,
      status: 'done',
      skip_reason: null,
      evaluators: ['judge:1'],
      rubric: [],
      value: 0.8,
      detail: {
        self_judged: false,
        judges_used: 1,
        judgements: [
          {
            judge_model: 'judge:1',
            value: 0.8,
            outcome: 'judged',
            criteria: { Relevance: { score: 4, reason: 'good' } },
          },
        ],
      },
      reference_result: null,
      created_at: '2026-01-01T00:00:01Z',
      finished_at: '2026-01-01T00:00:02Z',
    },
  ],
};

const SUMMARY = {
  window: '24h',
  turns: { total: 1, ok: 1 },
  quality: { mean: 0.8, evaluated: 1, below_threshold: 0, threshold: 0.5 },
  latency_ms: { p50: 100, p95: 150 },
  error_rate: 0,
  tokens: { prompt: 5, completion: 3 },
  evaluators: [{ model: 'judge:1', mean_score: 0.8, judged: 1, errors: 0 }],
  backlog: { pending: 0, skipped: {} },
  series: [{ bucket: '2026-01-01T00:00', count: 1, quality_mean: 0.8 }],
};

function baseRoutes(over: Record<string, unknown> = {}) {
  return {
    'GET /agents/1': AGENT,
    'GET /models': MODELS,
    'GET /agents/1/turns': [TURN],
    'GET /agents/1/turns/5': TURN_DETAIL,
    'GET /agents/1/summary': SUMMARY,
    'GET /agents/1/attention': [],
    ...over,
  };
}

function setup(routes: Record<string, unknown> = {}) {
  const api = mockApi(baseRoutes(routes));
  renderApp(<AgentPage />, { route: '/agents/1', path: '/agents/:id' });
  return { ...api, user: userEvent.setup() };
}

describe('header', () => {
  it('shows the agent name, kind and declared model', async () => {
    setup();
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('demo-chatbot');
    expect(screen.getByText('author:1')).toBeInTheDocument();
  });
});

describe('live tab', () => {
  it('connects to the SSE stream and reflects connection state', async () => {
    setup();
    await screen.findByRole('heading', { level: 1 });
    expect(await screen.findByText(/Live feed: connecting/)).toBeInTheDocument();
    const es = FakeEventSource.instances[0];
    act(() => es.open());
    expect(await screen.findByText(/Live feed: open/)).toBeInTheDocument();
  });

  it('lists turns with their evaluation status', async () => {
    setup();
    expect(await screen.findByText('hi there')).toBeInTheDocument();
    expect(screen.getByText(/evaluated 80%/)).toBeInTheDocument();
  });

  it('refreshes the header liveness badge when a turn starts (add-agent-playground)', async () => {
    let fetchCount = 0;
    setup({
      'GET /agents/1': () => {
        fetchCount += 1;
        // AGENT has no liveness field of its own - defaults come from AgentPage.test.tsx's setup()
        // merging it over baseRoutes; simulate the server recomputing liveness as "live" once this
        // agent's last_seen_at moves forward (touch_agent_liveness), which only a real ingest event
        // - here, the spawn's own turn.start - would actually cause.
        return fetchCount === 1 ? { ...AGENT, liveness: 'offline' } : { ...AGENT, liveness: 'live' };
      },
    });
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('offline');

    const es = FakeEventSource.instances[0];
    act(() => es.open());
    act(() => es.emit('turn_started', { turn_id: 6, input: 'a brand new task' }));

    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('live'),
    );
  });

  it('shows a new turn as soon as it starts, not only once it finishes (add-agent-playground)', async () => {
    let fetchCount = 0;
    const NEW_TURN = { ...TURN, id: 6, input: 'a brand new task', status: 'open', latest_evaluation: null };
    setup({
      'GET /agents/1/turns': () => {
        fetchCount += 1;
        return fetchCount === 1 ? [TURN] : [TURN, NEW_TURN];
      },
    });
    expect(await screen.findByText('hi there')).toBeInTheDocument();
    expect(screen.queryByText('a brand new task')).not.toBeInTheDocument();

    const es = FakeEventSource.instances[0];
    act(() => es.open());
    act(() => es.emit('turn_started', { turn_id: 6, input: 'a brand new task' }));

    expect(await screen.findByText('a brand new task')).toBeInTheDocument();
  });
});

describe('conversations tab', () => {
  it('opens a turn to show its spans and per-evaluator breakdown', async () => {
    const { user } = setup();
    await user.click(await screen.findByRole('tab', { name: 'Conversations' }));
    await user.click(await screen.findByText('hi there'));
    expect((await screen.findAllByText('hello!')).length).toBeGreaterThan(0);
    expect(screen.getByText('judge:1')).toBeInTheDocument();
    expect(screen.getByText(/Relevance/)).toBeInTheDocument();
  });

  it('re-evaluating posts to the evaluate endpoint and creates a new attempt', async () => {
    const secondAttempt = {
      ...TURN_DETAIL,
      evaluations: [
        ...TURN_DETAIL.evaluations,
        { ...TURN_DETAIL.evaluations[0], id: 10, attempt_no: 2 },
      ],
    };
    let evaluateCalled = false;
    const { user } = setup({
      'POST /agents/1/turns/5/evaluate': () => {
        evaluateCalled = true;
        return { ...TURN_DETAIL.evaluations[0], id: 10, attempt_no: 2 };
      },
      'GET /agents/1/turns/5': () => (evaluateCalled ? secondAttempt : TURN_DETAIL),
    });
    await user.click(await screen.findByRole('tab', { name: 'Conversations' }));
    await user.click(await screen.findByText('hi there'));
    await screen.findAllByText('hello!');
    await user.click(screen.getByRole('button', { name: 'Re-evaluate' }));
    expect(await screen.findByText(/Attempt 2/)).toBeInTheDocument();
  });
});

describe('quality tab', () => {
  it('shows quality, latency, evaluator strictness and needs-attention', async () => {
    const { user } = setup();
    await user.click(await screen.findByRole('tab', { name: 'Quality' }));
    expect((await screen.findAllByText('80%')).length).toBeGreaterThan(0);
    expect(screen.getByText('150 ms', { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/p95/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Evaluator strictness' })).toBeInTheDocument();
    expect(screen.getByText('Nothing below the threshold right now')).toBeInTheDocument();
  });
});

describe('settings tab', () => {
  it('marks the agent’s own model as ineligible to evaluate it', async () => {
    const { user } = setup();
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    const group = await screen.findByRole('group', { name: 'Evaluators' });
    const selfCheckbox = within(group).getByLabelText('author:1');
    expect(selfCheckbox).toBeDisabled();
    expect(within(group).getByText("one of this agent's own models")).toBeInTheDocument();
  });

  it('edits the agent kind and clears handoff_agent_names when moving away from router (add-agent-playground)', async () => {
    const { user, calls } = setup({
      'PATCH /agents/1': { ...AGENT, kind: 'reasoning' },
    });
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    const kindSelect = (await screen.findByLabelText('Kind')) as HTMLSelectElement;
    expect(kindSelect.value).toBe('chatbot');
    await user.selectOptions(kindSelect, 'reasoning');
    await user.click(screen.getAllByRole('button', { name: 'Save settings' })[0]);

    const patchCall = await vi.waitFor(() => {
      const found = calls.find((c) => c.method === 'PATCH' && c.path === '/agents/1');
      if (!found) throw new Error('no PATCH yet');
      return found;
    });
    expect(patchCall.body.kind).toBe('reasoning');
    expect(patchCall.body.handoff_agent_names).toEqual([]);
  });

  it('shows the hand-off agents picker once "Router" is selected, even before saving', async () => {
    const { user } = setup();
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    expect(screen.queryByRole('group', { name: 'Hand-off agents' })).not.toBeInTheDocument();
    const kindSelect = await screen.findByLabelText('Kind');
    await user.selectOptions(kindSelect, 'router');
    expect(await screen.findByRole('group', { name: 'Hand-off agents' })).toBeInTheDocument();
  });

  it('requires at least one hand-off agent before a router-kind agent can be saved', async () => {
    const { user } = setup({
      'GET /agents': [AGENT, { ...AGENT, id: 2, name: 'reasoner', kind: 'reasoning' }],
    });
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    const kindSelect = await screen.findByLabelText('Kind');
    await user.selectOptions(kindSelect, 'router');
    const group = await screen.findByRole('group', { name: 'Hand-off agents' });
    const saveButtons = screen.getAllByRole('button', { name: 'Save settings' });
    expect(saveButtons[0]).toBeDisabled();
    await user.click(within(group).getByLabelText('reasoner', { exact: false }));
    expect(saveButtons[0]).toBeEnabled();
  });

  it('offers a closed dropdown of task types and preserves an existing non-standard key as "(custom)"', async () => {
    const { user } = setup({
      'GET /agents/1': { ...AGENT, declared_models: { legacy_task: 'author:1' } },
    });
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    const taskSelect = (await screen.findByLabelText(
      'Task type for declared model 1',
    )) as HTMLSelectElement;
    expect(taskSelect.value).toBe('legacy_task'); // not silently reset to one of the standard options
    expect(Array.from(taskSelect.options).map((o) => o.value)).toEqual([
      '',
      'reasoning',
      'generation',
      'classification',
      'routing',
      'default',
      'legacy_task',
    ]);
    await user.selectOptions(taskSelect, 'reasoning'); // switching away still works normally
    expect(taskSelect.value).toBe('reasoning');
  });

  it('disables a model whose provider is unavailable, in both the evaluator and declared-model pickers', async () => {
    const unavailable = {
      name: '@oa/gpt-4o',
      digest: '',
      size_bytes: null,
      parameter_size: null,
      quantization: null,
      family: null,
      capabilities: [],
      thinking: false,
      source: 'cloud',
      provider: 'oa',
      provider_kind: 'openai',
      display_name: 'GPT-4o',
      reasoning: false,
      available: false,
      unavailable_reason: 'Last connection test failed: Incorrect API key provided.',
    };
    const { user } = setup({ 'GET /models': [...MODELS.slice(0, 2), unavailable] });
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    const group = await screen.findByRole('group', { name: 'Evaluators' });
    expect(within(group).getByLabelText('@oa/gpt-4o')).toBeDisabled();
    expect(
      within(group).getByText(/Last connection test failed: Incorrect API key provided/),
    ).toBeInTheDocument();
    const select = (await screen.findByLabelText(
      'Model for declared model 1',
    )) as HTMLSelectElement;
    const option = Array.from(select.options).find((o) => o.value === '@oa/gpt-4o');
    expect(option?.disabled).toBe(true);
  });

  it('gates a hosted evaluator behind a data-sharing acknowledgment, then saves', async () => {
    let acked = false;
    const { user } = setup({
      'PATCH /agents/1': () => {
        if (!acked)
          return jsonError(422, { code: 'ack_required', message: 'needs ack', provider: 'oa' });
        return {
          ...AGENT,
          eval_config: { ...AGENT.eval_config, evaluators: ['judge:1', '@oa/gpt-4o'] },
        };
      },
    });
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    const group = await screen.findByRole('group', { name: 'Evaluators' });
    await user.click(within(group).getByLabelText('@oa/gpt-4o'));
    await user.click(screen.getAllByRole('button', { name: 'Save settings' })[0]);
    const ackButton = await screen.findByRole('button', { name: 'Acknowledge and save' });
    acked = true;
    await user.click(ackButton);
    expect(await screen.findAllByRole('button', { name: 'Save settings' })).not.toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'Acknowledge and save' })).not.toBeInTheDocument();
  });

  it('gates a hosted declared model behind a data-sharing acknowledgment, then saves', async () => {
    let acked = false;
    const { user } = setup({
      'PATCH /agents/1': () => {
        if (!acked)
          return jsonError(422, {
            code: 'ack_required',
            message: 'needs ack',
            provider: 'azure-main',
          });
        return { ...AGENT, declared_models: { default: '@azure-main/gpt-4o-mini' } };
      },
    });
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    const select = await screen.findByLabelText('Model for declared model 1');
    await user.selectOptions(select, 'Custom (type manually)…');
    const modelField = await screen.findByLabelText('Model for declared model 1');
    await user.clear(modelField);
    await user.type(modelField, '@azure-main/gpt-4o-mini');
    await user.click(screen.getAllByRole('button', { name: 'Save settings' })[0]);
    const ackButton = await screen.findByRole('button', { name: 'Acknowledge and save' });
    acked = true;
    await user.click(ackButton);
    expect(await screen.findAllByRole('button', { name: 'Save settings' })).not.toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'Acknowledge and save' })).not.toBeInTheDocument();
  });

  it('gates a hosted declared-model fallback behind a data-sharing acknowledgment, then saves', async () => {
    let acked = false;
    const { user } = setup({
      'PATCH /agents/1': () => {
        if (!acked)
          return jsonError(422, {
            code: 'ack_required',
            message: 'needs ack',
            provider: 'azure-main',
          });
        return {
          ...AGENT,
          declared_models: { default: { model: 'author:1', fallback: '@azure-main/gpt-4o-mini' } },
        };
      },
    });
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    const fallbackField = await screen.findByLabelText('Fallback model for declared model 1');
    await user.type(fallbackField, '@azure-main/gpt-4o-mini');
    await user.click(screen.getAllByRole('button', { name: 'Save settings' })[0]);
    const ackButton = await screen.findByRole('button', { name: 'Acknowledge and save' });
    acked = true;
    await user.click(ackButton);
    expect(await screen.findAllByRole('button', { name: 'Save settings' })).not.toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'Acknowledge and save' })).not.toBeInTheDocument();
  });

  it('shows a non-ok gateway_sync result after saving a changed declared model', async () => {
    const { user } = setup({
      'PATCH /agents/1': {
        ...AGENT,
        gateway_sync: { default: { status: 'error', detail: 'gateway unreachable' } },
      },
    });
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    await user.click(screen.getAllByRole('button', { name: 'Save settings' })[0]);
    expect(await screen.findByText(/Gateway sync error/)).toBeInTheDocument();
    expect(screen.getByText(/gateway unreachable/)).toBeInTheDocument();
  });

  it('shows the new ingest token exactly once after rotation', async () => {
    const { user } = setup({
      'POST /agents/1/rotate-token': { ...AGENT, token: 'NEW-RAW-TOKEN' },
    });
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    await user.click(await screen.findByRole('button', { name: 'Rotate ingest token' }));
    expect(await screen.findByText('NEW-RAW-TOKEN')).toBeInTheDocument();
  });
});
