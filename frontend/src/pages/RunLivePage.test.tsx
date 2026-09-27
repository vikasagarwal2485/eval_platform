import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FakeEventSource } from '../test/fakeEventSource';
import { mockApi, renderApp } from '../test/utils';
import RunLivePage from './RunLivePage';

const CASES = [
  {
    id: 1,
    position: 0,
    category: 'classification',
    title: 'Spam check',
    prompt: 'p',
    system_prompt: null,
    expected: 'spam',
    config: {},
    rubric: null,
  },
  {
    id: 2,
    position: 1,
    category: 'reasoning',
    title: 'Bat and ball',
    prompt: 'p',
    system_prompt: null,
    expected: '5',
    config: {},
    rubric: null,
  },
];
const baseRun: Record<string, unknown> = {
  id: 5,
  name: 'Smoke',
  status: 'running',
  busy: true,
  config: {},
  judge_model: null,
  models: [],
  case_count: 2,
  progress: { completed: 0, total: 4 },
  error: null,
  ollama_version: '0.34.2',
  parent_run_id: null,
  created_at: '2026-01-01T00:00:00Z',
  started_at: null,
  finished_at: null,
  cases: CASES,
  current: {},
};

function setup(run: Record<string, unknown> = baseRun, extra: Record<string, unknown> = {}) {
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
  const api = mockApi({
    'GET /runs/5': run,
    'GET /runs/5/results': { attempt_id: 1, results: [] },
    'POST /runs/5/cancel': { status: 'cancelling' },
    ...extra,
  });
  renderApp(<RunLivePage />, { route: '/runs/5/live', path: '/runs/:id/live' });
  return { ...api, user: userEvent.setup() };
}
const es = () => FakeEventSource.instances.at(-1)!;

afterEach(() => vi.unstubAllGlobals());

describe('9.5 live run view', () => {
  it('shows progress, the current model/case, streaming preview and results as events arrive', async () => {
    setup();
    await screen.findByRole('progressbar', { name: 'Run progress' });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(es().url).toBe('/api/runs/5/events');

    act(() => {
      es().open();
      es().emit('run_started', { total: 4 });
      es().emit('request_started', {
        model: 'qwen3:8b',
        case_id: 1,
        case_title: 'Spam check',
        repeat: 0,
      });
      es().emit('token', {
        model: 'qwen3:8b',
        case_id: 1,
        answer: 'sp',
        thinking: 'Let me think. ',
      });
      es().emit('token', { model: 'qwen3:8b', case_id: 1, answer: 'am', thinking: '' });
    });
    expect(screen.getByText(/Running qwen3:8b · Spam check/)).toBeInTheDocument();
    const preview = screen.getByRole('region', { name: 'Streaming preview' });
    expect(within(preview).getByText('spam')).toBeInTheDocument();
    expect(within(preview).getByText(/Thinking \(14 chars\)/)).toBeInTheDocument();

    act(() => {
      es().emit('result_completed', {
        result_id: 11,
        model: 'qwen3:8b',
        case_id: 1,
        repeat: 0,
        status: 'ok',
        outcome: 'correct',
        value: 1,
        latency_ms: 6800,
        tokens_per_s: 40.1,
        is_cold: false,
        error: null,
      });
      es().emit('progress', { completed: 1, total: 4 });
    });
    const bar = screen.getByRole('progressbar', { name: 'Run progress' });
    expect(bar).toHaveAttribute('aria-valuenow', '1');
    expect(bar).toHaveAttribute('aria-valuemax', '4');
    expect(screen.getByText('25%')).toBeInTheDocument();
    const table = screen.getByRole('table');
    expect(within(table).getByText('qwen3:8b')).toBeInTheDocument();
    expect(within(table).getByText('Spam check')).toBeInTheDocument();
    expect(within(table).getByText('correct')).toBeInTheDocument();
    expect(within(table).getByText('6.80 s')).toBeInTheDocument();

    act(() => {
      es().emit('result_completed', {
        result_id: 12,
        model: 'qwen3:8b',
        case_id: 2,
        repeat: 0,
        status: 'error',
        outcome: 'error',
        value: 0,
        latency_ms: null,
        tokens_per_s: null,
        is_cold: false,
        error: 'timed out',
      });
    });
    expect(within(screen.getByRole('table')).getByText('error')).toBeInTheDocument();
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(3); // header + 2
  });

  it('shows the judge stage', async () => {
    setup();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      es().emit('scoring_started', { judge_model: 'gemma4:e4b' });
      es().emit('scoring_progress', { done: 1, total: 3 });
    });
    expect(screen.getByText(/Scoring generated answers with the judge… 1\/3/)).toBeInTheDocument();
  });

  it('cancels the run', async () => {
    const { user, calls } = setup();
    await user.click(await screen.findByRole('button', { name: 'Cancel run' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path === '/runs/5/cancel')).toBe(true),
    );
    expect(await screen.findByRole('button', { name: 'Cancelling…' })).toBeDisabled();
  });

  it('shows a reconnecting indicator when the stream drops', async () => {
    setup();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => es().open());
    act(() => es().drop());
    expect(screen.getByText('reconnecting…')).toBeInTheDocument();
  });

  it('offers results once the run has finished, with no cancel button or event stream', async () => {
    setup({ ...baseRun, status: 'completed', busy: false, progress: { completed: 4, total: 4 } });
    expect(await screen.findByRole('link', { name: 'View results' })).toHaveAttribute(
      'href',
      '/runs/5',
    );
    expect(screen.queryByRole('button', { name: 'Cancel run' })).toBeNull();
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it('reports failed and cancelled runs', async () => {
    setup({
      ...baseRun,
      status: 'failed',
      busy: false,
      error: 'Ollama unreachable after 3 attempts',
    });
    expect(await screen.findByText(/Ollama unreachable after 3 attempts/)).toBeInTheDocument();
  });

  it('renders database results after a reload (no events needed)', async () => {
    setup(
      { ...baseRun, status: 'completed', busy: false, progress: { completed: 1, total: 1 } },
      {
        'GET /runs/5/results': {
          attempt_id: 1,
          results: [
            {
              id: 3,
              model: 'gemma4:e4b',
              model_id: 1,
              case_id: 2,
              category: 'reasoning',
              repeat: 0,
              status: 'ok',
              output: '5',
              thinking: null,
              error: null,
              is_cold: false,
              sent_prompt: '',
              template_version: 'v1',
              latency_ms: 15300,
              ttft_ms: 300,
              tokens_per_s: 46.5,
              output_tokens: 700,
              metrics: {},
              scores: [],
              primary: { value: 1, outcome: 'correct' },
            },
          ],
        },
      },
    );
    expect(await screen.findByText('gemma4:e4b')).toBeInTheDocument();
    expect(screen.getByText('Bat and ball')).toBeInTheDocument();
    expect(screen.getByText('15.3 s')).toBeInTheDocument();
  });

  it('handles a missing run', async () => {
    setup(baseRun, {
      'GET /runs/5': () =>
        new Response(JSON.stringify({ detail: 'run 5 not found' }), { status: 404 }),
    });
    expect(await screen.findByText(/run 5 not found/)).toBeInTheDocument();
  });
});

describe('6.5 enterprise models in the live view', () => {
  const withCloudModel = {
    ...baseRun,
    models: [
      {
        id: 1,
        name: '@oa/gpt-4o',
        digest: '',
        source: 'cloud',
        provider: 'oa',
        provider_kind: 'openai',
      },
    ],
  };

  it('shows a cloud badge in the "Running" status line for an enterprise model', async () => {
    setup(withCloudModel);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      es().open();
      es().emit('run_started', { total: 2 });
      es().emit('request_started', {
        model: '@oa/gpt-4o',
        case_id: 1,
        case_title: 'Spam check',
        repeat: 0,
      });
    });
    const status = screen.getByText(/Running/).closest('p') as HTMLElement;
    expect(status).toHaveTextContent('Running @oa/gpt-4o');
    expect(within(status).getByText('cloud · oa')).toBeInTheDocument();
  });

  it('shows a cloud badge in the streaming preview heading', async () => {
    setup(withCloudModel);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      es().open();
      es().emit('request_started', { model: '@oa/gpt-4o', case_id: 1, repeat: 0 });
      es().emit('token', { model: '@oa/gpt-4o', case_id: 1, answer: 'hi', thinking: '' });
    });
    const preview = screen.getByRole('region', { name: 'Streaming preview' });
    expect(within(preview).getByText('cloud · oa')).toBeInTheDocument();
  });

  it('shows a cloud badge for the model in the completed-requests table', async () => {
    setup(withCloudModel);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      es().open();
      es().emit('result_completed', {
        result_id: 20,
        model: '@oa/gpt-4o',
        case_id: 1,
        repeat: 0,
        status: 'ok',
        outcome: 'correct',
        value: 1,
        latency_ms: 900,
        tokens_per_s: 55,
        is_cold: false,
        error: null,
      });
    });
    const table = screen.getByRole('table');
    const row = within(table).getByText('@oa/gpt-4o').closest('tr') as HTMLElement;
    expect(within(row).getByText('cloud · oa')).toBeInTheDocument();
  });
});
