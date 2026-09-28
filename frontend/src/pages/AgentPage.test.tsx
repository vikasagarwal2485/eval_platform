import { act, screen, within } from '@testing-library/react';
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
  declared_model: 'author:1',
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
    expect(within(group).getByText("this agent's own model")).toBeInTheDocument();
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
    await user.click(screen.getByRole('button', { name: 'Save settings' }));
    const ackButton = await screen.findByRole('button', { name: 'Acknowledge and save' });
    acked = true;
    await user.click(ackButton);
    expect(await screen.findByRole('button', { name: 'Save settings' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Acknowledge and save' })).not.toBeInTheDocument();
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
