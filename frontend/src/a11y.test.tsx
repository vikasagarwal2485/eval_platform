import axe from 'axe-core';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { FakeEventSource } from './test/fakeEventSource';
import { result, row, runOf, summary, THREE_MODELS } from './test/fixtures';
import { baseRoutes, CLOUD_MODELS, jsonError, mockApi, MODELS, renderApp } from './test/utils';

/** jsdom has no layout, so colour-contrast is checked by the palette validator instead. */
async function audit() {
  const r = await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } });
  return r.violations.map(
    (v) =>
      `${v.impact} ${v.id}: ${v.help} -> ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`,
  );
}

const RUN = runOf(['alpha:1', 'bravo:2', 'charlie:3']);
const RESULTS = [
  result('alpha:1', 1, 'classification', 'correct', {
    scores: [{ kind: 'auto', value: 1, outcome: 'correct', detail: { predicted: 'spam' } }],
  }),
  result('bravo:2', 1, 'classification', 'wrong', { thinking: 'hmm' }),
  result('alpha:1', 3, 'generation', 'judged', {
    primary: { value: 0.8, outcome: 'judged' },
    scores: [
      {
        kind: 'judge',
        value: 0.8,
        outcome: 'judged',
        detail: { criteria: { A: { score: 4, reason: 'ok' } } },
      },
    ],
  }),
];
const routes = {
  ...baseRoutes,
  'GET /runs': [RUN],
  'GET /runs/5': RUN,
  'GET /runs/5/summary': summary(THREE_MODELS),
  'GET /runs/5/results': { attempt_id: 1, results: RESULTS },
};

function app(path: string) {
  vi.stubGlobal('EventSource', FakeEventSource);
  mockApi(routes);
  return renderApp(<App />, { route: path, path: '*', stubLive: false });
}
afterEach(() => vi.unstubAllGlobals());

describe('9.10 accessibility (axe, no violations)', () => {
  it('run setup', async () => {
    app('/');
    await screen.findByRole('checkbox', { name: 'qwen3:8b' });
    await screen.findByRole('checkbox', { name: 'Starter suite' });
    expect(await audit()).toEqual([]);
  });

  it('run setup: ad-hoc tab', async () => {
    app('/');
    await userEvent.setup().click(await screen.findByRole('tab', { name: /ad-hoc prompt/i }));
    expect(await audit()).toEqual([]);
  });

  it('live run', async () => {
    app('/runs/5/live');
    await screen.findByRole('table');
    expect(await audit()).toEqual([]);
  });

  it('results: overview with charts', async () => {
    app('/runs/5');
    await screen.findByRole('table', { name: 'Model leaderboard' });
    await screen.findByRole('heading', { name: 'Quality vs. speed' });
    expect(await audit()).toEqual([]);
  });

  it('results: cases', async () => {
    app('/runs/5');
    await userEvent.setup().click(await screen.findByRole('tab', { name: 'Cases' }));
    await screen.findAllByRole('region');
    expect(await audit()).toEqual([]);
  });

  it('suites and history', async () => {
    const { unmount } = app('/suites');
    await screen.findByRole('region', { name: 'Suite Starter suite' });
    expect(await audit()).toEqual([]);
    unmount();
    app('/history');
    await screen.findByRole('table', { name: 'Runs' });
    expect(await audit()).toEqual([]);
  });
});

describe('9.10 loading, empty and error states', () => {
  it('setup: backend unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    renderApp(<App />, { route: '/', path: '*' });
    expect(await screen.findByText(/Cannot reach the evaluation backend/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start evaluation/i })).toBeDisabled();
  });

  it('shows loading indicators before data arrives', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    );
    renderApp(<App />, { route: '/history', path: '*' });
    expect(screen.getByRole('status')).toHaveTextContent('Loading runs');
  });

  it.each([
    ['/history', 'Could not load runs.'],
    ['/suites', 'Could not load suites.'],
    ['/runs/5', 'Could not load the run.'],
    ['/runs/5/live', 'Could not load the run.'],
  ])('%s shows an error', async (path, text) => {
    mockApi({
      'GET /runs': () => jsonError(500, 'db exploded'),
      'GET /suites': () => jsonError(500, 'db exploded'),
      'GET /runs/5': () => jsonError(404, 'run 5 not found'),
    });
    renderApp(<App />, { route: path, path: '*', stubLive: false });
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it('results: run with no results yet', async () => {
    mockApi({
      ...routes,
      'GET /runs/5/summary': summary([]),
      'GET /runs/5/results': { attempt_id: null, results: [] },
    });
    renderApp(<App />, { route: '/runs/5', path: '*' });
    expect(await screen.findByText('No results yet')).toBeInTheDocument();
  });

  it('results: summary failure does not blank the page', async () => {
    mockApi({ ...routes, 'GET /runs/5/summary': () => jsonError(500, 'summary failed') });
    renderApp(<App />, { route: '/runs/5', path: '*' });
    expect(await screen.findByText(/summary failed/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Export CSV' })).toBeInTheDocument();
  });

  it('every icon-free control has an accessible name', async () => {
    app('/runs/5');
    await screen.findByRole('table', { name: 'Model leaderboard' });
    for (const b of screen.getAllByRole('button')) expect(b).toHaveAccessibleName();
    for (const c of screen.getAllByRole('checkbox')) expect(c).toHaveAccessibleName();
    for (const s of screen.getAllByRole('combobox')) expect(s).toHaveAccessibleName();
  });
});

describe('9.10 keyboard operability', () => {
  it('sorts the leaderboard and switches tabs with the keyboard alone', async () => {
    const user = userEvent.setup();
    app('/runs/5');
    await screen.findByRole('table', { name: 'Model leaderboard' });
    const sortBtn = screen.getAllByRole('button', { name: /Tokens\/s/ })[0];
    sortBtn.focus();
    await user.keyboard('{Enter}');
    expect(sortBtn.closest('th')).toHaveAttribute('aria-sort', 'descending');
    await user.keyboard(' ');
    expect(sortBtn.closest('th')).toHaveAttribute('aria-sort', 'ascending');

    screen.getByRole('tab', { name: 'Cases' }).focus();
    await user.keyboard('{Enter}');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Cases' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('offers a skip link and labelled landmarks', async () => {
    app('/');
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main');
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main');
  });

  it('reaches every chart mark by keyboard', async () => {
    const user = userEvent.setup();
    app('/runs/5');
    await screen.findByRole('heading', { name: 'Score by category' });
    const marks = screen.getAllByTestId('score-bar');
    expect(marks.every((m) => m.getAttribute('tabindex') === '0')).toBe(true);
    marks[0].focus();
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});

void row;

describe('cross-model judging accessibility (5.6)', () => {
  const crossSummary = summary(
    THREE_MODELS.slice(0, 2).map((r) => ({ ...r, judges_per_answer: 1 })),
    {
      attempt: { id: 3, judge_model: null, judge_mode: 'cross_model' },
      attempts: [
        { id: 3, judge_model: null, judge_mode: 'cross_model', created_at: '2026-01-03T00:00:00Z' },
      ],
      judging: {
        mode: 'cross_model',
        judges: [
          { model: 'alpha:1', judged: 3, errors: 0, mean_score: 0.8, reasoning_mean_score: null },
          { model: 'bravo:2', judged: 2, errors: 1, mean_score: 0.4, reasoning_mean_score: null },
        ],
      },
    },
  );
  const crossResults = [
    result('alpha:1', 3, 'generation', 'judged', {
      primary: { value: 0.6, outcome: 'judged' },
      scores: [
        {
          kind: 'judge',
          value: 0.6,
          outcome: 'judged',
          detail: {
            mode: 'cross_model',
            judgements: [
              {
                judge_model: 'bravo:2',
                value: 0.6,
                outcome: 'judged',
                criteria: { Relevance: { score: 3, reason: 'fine' } },
              },
              { judge_model: 'charlie:3', value: null, outcome: 'error', error: 'bad json' },
            ],
          },
        },
      ],
    }),
  ];
  const crossRoutes = {
    ...routes,
    'GET /runs/5/summary': crossSummary,
    'GET /runs/5/results': { attempt_id: 3, results: crossResults },
  };
  const appWith = (path: string, r: Record<string, unknown>) => {
    vi.stubGlobal('EventSource', FakeEventSource);
    mockApi(r);
    return renderApp(<App />, { route: path, path: '*', stubLive: false });
  };

  it('run setup: cross-model chosen, with note and estimate', async () => {
    const user = userEvent.setup();
    appWith('/', routes);
    await user.click(await screen.findByRole('checkbox', { name: 'qwen3:8b' }));
    await user.click(screen.getByRole('checkbox', { name: 'gemma4:e4b' }));
    await user.click(await screen.findByRole('checkbox', { name: 'Starter suite' }));
    await user.click(screen.getByRole('radio', { name: 'Cross-model judging' }));
    expect(screen.getByTestId('judge-estimate')).toBeInTheDocument();
    expect(await audit()).toEqual([]);
  });

  it('run setup: disabled cross-model option and the self-judging warning', async () => {
    const user = userEvent.setup();
    appWith('/', routes);
    await user.click(await screen.findByRole('checkbox', { name: 'qwen3:8b' }));
    expect(screen.getByRole('radio', { name: 'Cross-model judging' })).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    await user.selectOptions(screen.getByLabelText('Judge model'), 'qwen3:8b');
    expect(screen.getByText(/both judge and one of the models/)).toBeInTheDocument();
    expect(await audit()).toEqual([]);
  });

  it('results: cross-judged leaderboard and judge strictness card', async () => {
    appWith('/runs/5', crossRoutes);
    await screen.findByRole('table', { name: 'Judge strictness' });
    expect(screen.getAllByText('cross-judged · 1 judge').length).toBeGreaterThan(0);
    expect(await audit()).toEqual([]);
  });

  it('results: per-judge breakdown in the case drill-down', async () => {
    appWith('/runs/5', crossRoutes);
    await userEvent.setup().click(await screen.findByRole('tab', { name: 'Cases' }));
    await screen.findByRole('list', { name: 'Judge by judge' });
    expect(await audit()).toEqual([]);
  });

  it('the judging radio group is keyboard-operable and skips the disabled option', async () => {
    const user = userEvent.setup();
    appWith('/', routes);
    await user.click(await screen.findByRole('checkbox', { name: 'qwen3:8b' })); // one model: cross disabled
    const none = screen.getByRole('radio', { name: 'No judge' });
    none.focus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('radio', { name: 'Single judge model' })).toBeChecked();
    await user.keyboard('{ArrowDown}'); // the disabled cross-model option is skipped, wrapping to the first
    expect(none).toBeChecked();
    // with two models it becomes reachable
    await user.click(screen.getByRole('checkbox', { name: 'gemma4:e4b' }));
    screen.getByRole('radio', { name: 'Single judge model' }).focus();
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('radio', { name: 'Cross-model judging' })).toBeChecked();
  });

  it('every new control has an accessible name and description', async () => {
    const user = userEvent.setup();
    appWith('/', routes);
    await user.click(await screen.findByRole('checkbox', { name: 'qwen3:8b' }));
    for (const radio of screen.getAllByRole('radio', { name: /judg/i })) {
      expect(radio).toHaveAccessibleName();
      expect(radio).toHaveAccessibleDescription();
    }
  });
});

describe('enterprise providers accessibility (6.6)', () => {
  const providerFixture = (over = {}) => ({
    id: 1,
    kind: 'openai',
    name: 'oa',
    key_env: 'OA_KEY',
    base_url: null,
    key_available: true,
    data_sharing_acknowledged_at: '2026-01-01T00:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
    models: [
      {
        id: 10,
        model_id: 'gpt-4o',
        ref: '@oa/gpt-4o',
        display_name: 'gpt-4o',
        enabled: true,
        reasoning: false,
      },
    ],
    ...over,
  });

  const MIXED = [...MODELS, ...CLOUD_MODELS];
  const cloudRun = runOf(['alpha:1', '@oa/gpt-4o']);
  const cloudResults = [
    result('alpha:1', 1, 'classification', 'correct'),
    result('@oa/gpt-4o', 1, 'classification', 'correct', {
      model_version: 'gpt-4o-2024-08-06',
      attempts: 2,
      params_ignored: [
        { name: 'num_ctx', reason: 'context size is not configurable for this provider' },
      ],
    }),
  ];
  const cloudRoutes = {
    ...routes,
    'GET /models': MIXED,
    'GET /providers': [providerFixture()],
    'GET /runs/5': cloudRun,
    'GET /runs/5/summary': summary([
      row('alpha:1', { cls: 1 }),
      row('@oa/gpt-4o', { cls: 1, cloud: true }),
    ]),
    'GET /runs/5/results': { attempt_id: 1, results: cloudResults },
  };

  const appWith = (path: string, r: Record<string, unknown>) => {
    vi.stubGlobal('EventSource', FakeEventSource);
    mockApi(r);
    return renderApp(<App />, { route: path, path: '*', stubLive: false });
  };

  it('providers page: empty state', async () => {
    appWith('/providers', { ...routes, 'GET /providers': [] });
    expect(await screen.findByText('No providers registered yet')).toBeInTheDocument();
    expect(await audit()).toEqual([]);
  });

  it('providers page: with a registered provider and its model', async () => {
    appWith('/providers', { ...routes, 'GET /providers': [providerFixture()] });
    await screen.findByRole('region', { name: 'Provider oa' });
    expect(await audit()).toEqual([]);
  });

  it('run setup: grouped model picker with local and enterprise models', async () => {
    appWith('/', cloudRoutes);
    await screen.findByRole('checkbox', { name: '@oa/gpt-4o' });
    expect(await audit()).toEqual([]);
  });

  it('run setup: data-sharing notice for an enterprise contestant', async () => {
    const user = userEvent.setup();
    appWith('/', cloudRoutes);
    await user.click(await screen.findByRole('checkbox', { name: 'qwen3:8b' }));
    await user.click(screen.getByRole('checkbox', { name: '@oa/gpt-4o' }));
    expect(await screen.findByText(/This run will send data to/)).toBeInTheDocument();
    expect(await audit()).toEqual([]);
  });

  it('results: cloud badge and per-result parameter details in the drill-down', async () => {
    appWith('/runs/5', cloudRoutes);
    await userEvent.setup().click(await screen.findByRole('tab', { name: 'Cases' }));
    await screen.findByText('Not applied:', { exact: false });
    expect(await audit()).toEqual([]);
  });

  it('run setup: the grouped model picker is keyboard-operable with accessible names', async () => {
    appWith('/', cloudRoutes);
    const gpt = await screen.findByRole('checkbox', { name: '@oa/gpt-4o' });
    expect(gpt).toHaveAccessibleName('@oa/gpt-4o');
    gpt.focus();
    expect(gpt).toHaveFocus();
    const claude = screen.getByRole('checkbox', { name: '@an/claude' });
    expect(claude).toBeDisabled();
    expect(claude).toHaveAccessibleDescription(/environment variable AN_KEY is empty/);
  });

  it('providers page controls have accessible names', async () => {
    appWith('/providers', { ...routes, 'GET /providers': [providerFixture()] });
    const card = await screen.findByRole('region', { name: 'Provider oa' });
    for (const b of screen.getAllByRole('button')) expect(b).toHaveAccessibleName();
    for (const c of screen.getAllByRole('checkbox')) expect(c).toHaveAccessibleName();
    expect(card).toBeInTheDocument();
  });
});

describe('live agent evaluation accessibility (6.6)', () => {
  const agentFixture = (over = {}) => ({
    id: 1,
    name: 'demo-chatbot',
    kind: 'chatbot',
    declared_model: 'qwen3:8b',
    status: 'active',
    liveness: 'idle',
    token_prefix: 'abcd1234',
    eval_config: {
      evaluators: ['llama3:8b'],
      sample_rate: 1,
      quiet_period_s: 20,
      context_turns: 4,
      attention_threshold: 0.5,
      abandon_after_s: 600,
      retention_days: null,
    },
    rubric: null,
    provider_acks: [],
    last_seen_at: '2026-01-01T00:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
    ...over,
  });

  const agentTurn = (over = {}) => ({
    id: 5,
    external_id: 't1',
    session_id: 's1',
    seq: 0,
    status: 'ok',
    input: 'What is the weather like?',
    output: "I don't have live weather access, but I can help with something else.",
    reference: null,
    error: null,
    models: ['qwen3:8b'],
    models_unknown: false,
    truncated: false,
    latency_ms: 120,
    prompt_tokens: 12,
    completion_tokens: 20,
    started_at: '2026-01-01T00:00:00Z',
    ended_at: '2026-01-01T00:00:01Z',
    latest_evaluation: { status: 'done', value: 0.8 },
    ...over,
  });

  const agentTurnDetail = {
    ...agentTurn(),
    spans: [
      {
        id: 1,
        kind: 'llm',
        model: 'qwen3:8b',
        name: null,
        input: {},
        output: agentTurn().output,
        thinking: null,
        error: null,
        started_at: null,
        ended_at: null,
        latency_ms: 100,
        ttft_ms: null,
        prompt_tokens: 12,
        completion_tokens: 20,
      },
    ],
    evaluations: [
      {
        id: 9,
        attempt_no: 1,
        status: 'done',
        skip_reason: null,
        evaluators: ['llama3:8b'],
        rubric: [],
        value: 0.8,
        detail: {
          self_judged: false,
          judges_used: 1,
          judgements: [
            {
              judge_model: 'llama3:8b',
              value: 0.8,
              outcome: 'judged',
              criteria: { Relevance: { score: 4, reason: 'on topic' } },
            },
          ],
        },
        reference_result: null,
        created_at: '2026-01-01T00:00:01Z',
        finished_at: '2026-01-01T00:00:02Z',
      },
    ],
  };

  const agentSummaryFixture = {
    window: '24h',
    turns: { total: 1, ok: 1 },
    quality: { mean: 0.8, evaluated: 1, below_threshold: 0, threshold: 0.5 },
    latency_ms: { p50: 100, p95: 150 },
    error_rate: 0,
    tokens: { prompt: 12, completion: 20 },
    evaluators: [{ model: 'llama3:8b', mean_score: 0.8, judged: 1, errors: 0 }],
    backlog: { pending: 0, skipped: {} },
    series: [{ bucket: '2026-01-01T00:00', count: 1, quality_mean: 0.8 }],
  };

  const agentRoutes = {
    ...baseRoutes,
    'GET /agents': [agentFixture()],
    'GET /agents/1': agentFixture(),
    'GET /agents/1/turns': [agentTurn()],
    'GET /agents/1/turns/5': agentTurnDetail,
    'GET /agents/1/summary': agentSummaryFixture,
    'GET /agents/1/attention': [],
  };

  const appWith = (path: string, r: Record<string, unknown>) => {
    vi.stubGlobal('EventSource', FakeEventSource);
    mockApi(r);
    return renderApp(<App />, { route: path, path: '*', stubLive: false });
  };

  it('agents list: empty state', async () => {
    appWith('/agents', { ...baseRoutes, 'GET /agents': [] });
    expect(await screen.findByText('No agents connected yet')).toBeInTheDocument();
    expect(await audit()).toEqual([]);
  });

  it('agents list: with a registered agent', async () => {
    appWith('/agents', agentRoutes);
    expect(await screen.findByRole('link', { name: /demo-chatbot/ })).toBeInTheDocument();
    expect(await audit()).toEqual([]);
  });

  it('agent detail: live tab', async () => {
    appWith('/agents/1', agentRoutes);
    await screen.findByText('What is the weather like?', { exact: false });
    expect(await audit()).toEqual([]);
  });

  it('agent detail: conversations tab with the per-evaluator breakdown open', async () => {
    const user = userEvent.setup();
    appWith('/agents/1', agentRoutes);
    await user.click(await screen.findByRole('tab', { name: 'Conversations' }));
    await user.click(await screen.findByText('What is the weather like?', { exact: false }));
    await screen.findByText('llama3:8b');
    expect(await audit()).toEqual([]);
  });

  it('agent detail: quality tab', async () => {
    const user = userEvent.setup();
    appWith('/agents/1', agentRoutes);
    await user.click(await screen.findByRole('tab', { name: 'Quality' }));
    await screen.findByRole('heading', { name: 'Evaluator strictness' });
    expect(await audit()).toEqual([]);
  });

  it('agent detail: settings tab with the evaluator picker', async () => {
    const user = userEvent.setup();
    appWith('/agents/1', agentRoutes);
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    await screen.findByRole('group', { name: 'Evaluators' });
    expect(await audit()).toEqual([]);
  });

  it('agent detail: self-evaluator is disabled with an accessible description', async () => {
    appWith('/agents/1', agentRoutes);
    await userEvent.setup().click(await screen.findByRole('tab', { name: 'Settings' }));
    const own = await screen.findByRole('checkbox', { name: 'qwen3:8b' });
    expect(own).toBeDisabled();
    expect(own).toHaveAccessibleDescription(/cannot evaluate its own declared model/);
  });

  it('agent detail: hosted evaluator needing acknowledgment is explained', async () => {
    appWith('/agents/1', { ...agentRoutes, 'GET /models': [...MODELS, ...CLOUD_MODELS] });
    await userEvent.setup().click(await screen.findByRole('tab', { name: 'Settings' }));
    const gpt = await screen.findByRole('checkbox', { name: '@oa/gpt-4o' });
    expect(gpt).toHaveAccessibleDescription(/Acknowledge data sharing/);
    expect(await audit()).toEqual([]);
  });

  it('agent detail: tabs are keyboard-operable with accessible names', async () => {
    appWith('/agents/1', agentRoutes);
    const tabs = await screen.findAllByRole('tab');
    for (const t of tabs) expect(t).toHaveAccessibleName();
    tabs[0].focus();
    expect(tabs[0]).toHaveFocus();
  });

  it('agent detail: every control has an accessible name', async () => {
    const user = userEvent.setup();
    appWith('/agents/1', agentRoutes);
    await user.click(await screen.findByRole('tab', { name: 'Settings' }));
    await screen.findByRole('group', { name: 'Evaluators' });
    for (const b of screen.getAllByRole('button')) expect(b).toHaveAccessibleName();
    for (const c of screen.getAllByRole('checkbox')) expect(c).toHaveAccessibleName();
  });
});
