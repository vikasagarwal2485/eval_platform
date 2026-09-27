import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { mockApi, renderApp } from '../test/utils';
import { composite, EQUAL_WEIGHTS } from '../lib/scores';
import { row, summary, THREE_MODELS, runOf, result } from '../test/fixtures';
import ResultsPage from '../pages/ResultsPage';

const board = () => screen.getByRole('table', { name: 'Model leaderboard' });
const modelsInTable = () =>
  within(screen.getByRole('table', { name: 'Model leaderboard' }))
    .getAllByRole('row')
    .slice(1)
    .map((r) => within(r).getAllByRole('cell')[1].textContent);

function setup(rows = THREE_MODELS, extra: Record<string, unknown> = {}, sumExtra = {}) {
  mockApi({
    'GET /runs/5': runOf(rows.map((r) => r.model)),
    'GET /runs/5/summary': summary(rows, sumExtra),
    'GET /runs/5/results': { attempt_id: 1, results: [] },
    'GET /models': [],
    ...extra,
  });
  renderApp(<ResultsPage />, { route: '/runs/5', path: '/runs/:id' });
  return userEvent.setup();
}

describe('composite()', () => {
  it('matches the server rule, including renormalisation over missing categories', () => {
    const cats = {
      classification: { score: 1, scored: 1, total: 1, errors: 0, unparseable: 0 },
      generation: { score: 0.5, scored: 1, total: 1, errors: 0, unparseable: 0 },
    };
    expect(composite(cats, { classification: 0.4, reasoning: 0.4, generation: 0.2 })).toBeCloseTo(
      (0.4 * 1 + 0.2 * 0.5) / 0.6,
    );
    expect(composite(cats, EQUAL_WEIGHTS)).toBeCloseTo(0.75);
    expect(composite({}, EQUAL_WEIGHTS)).toBeNull();
    expect(
      composite(
        { generation: { score: null, scored: 0, total: 1, errors: 0, unparseable: 0 } },
        EQUAL_WEIGHTS,
      ),
    ).toBeNull();
  });
});

describe('9.6 leaderboard', () => {
  it('ranks models by composite and shows category scores, speed and scored counts', async () => {
    setup();
    await screen.findByRole('table', { name: 'Model leaderboard' });
    // alpha: (1+.5+.75)/3=.75 ; bravo: (.5+1+.5)/3=.667 ; charlie: (.75+.25+1)/3=.667
    expect(modelsInTable()[0]).toBe('alpha:1');
    const first = within(screen.getByRole('table', { name: 'Model leaderboard' })).getAllByRole(
      'row',
    )[1];
    expect(within(first).getByText('75.0%')).toBeInTheDocument();
    expect(within(first).getByText('6.80 s')).toBeInTheDocument();
    expect(within(first).getAllByText('2/2').length).toBeGreaterThan(0);
  });

  it('6.5: marks an enterprise model with a cloud badge and provider, and shows local models plainly', async () => {
    const rows = [
      row('alpha:1', { cls: 1, rea: 1, gen: 1, latency: 900, tps: 60 }),
      row('@oa/gpt-4o', { cls: 1, rea: 1, gen: 1, latency: 1200, tps: 55, cloud: true }),
    ];
    setup(rows);
    await screen.findByRole('table', { name: 'Model leaderboard' });
    const table = board();
    const cloudRow = within(table).getByText('@oa/gpt-4o').closest('tr') as HTMLElement;
    expect(within(cloudRow).getByText('cloud · oa')).toBeInTheDocument();
    const localRow = within(table).getByText('alpha:1').closest('tr') as HTMLElement;
    expect(within(localRow).queryByText(/cloud/)).toBeNull();
  });

  it('sorts by any column and toggles direction', async () => {
    const user = setup();
    await screen.findByRole('table', { name: 'Model leaderboard' });
    const header = (name: string) =>
      within(board()).getByRole('columnheader', { name: new RegExp(name) });
    const sortBy = (name: RegExp) => user.click(within(board()).getByRole('button', { name }));

    await sortBy(/Tokens\/s/);
    expect(modelsInTable()).toEqual(['bravo:2', 'alpha:1', 'charlie:3']); // fastest first
    expect(header('Tokens/s')).toHaveAttribute('aria-sort', 'descending');

    await sortBy(/Tokens\/s/);
    expect(modelsInTable()).toEqual(['charlie:3', 'alpha:1', 'bravo:2']);
    expect(header('Tokens/s')).toHaveAttribute('aria-sort', 'ascending');

    await sortBy(/Latency/);
    expect(modelsInTable()).toEqual(['bravo:2', 'alpha:1', 'charlie:3']); // lower latency first by default
    await sortBy(/^Model/);
    expect(modelsInTable()).toEqual(['alpha:1', 'bravo:2', 'charlie:3']);
  });

  it('sorts models with missing values last in either direction', async () => {
    const rows = [
      ...THREE_MODELS,
      row('delta:4', { cls: 1, rea: 1, gen: 1, latency: null, tps: null }),
    ];
    const user = setup(rows);
    await screen.findByRole('table', { name: 'Model leaderboard' });
    const sortBy = (name: RegExp) => user.click(within(board()).getByRole('button', { name }));
    await sortBy(/Tokens\/s/);
    expect(modelsInTable().at(-1)).toBe('delta:4');
    await sortBy(/Tokens\/s/);
    expect(modelsInTable().at(-1)).toBe('delta:4');
  });

  it('recomputes composites and ranking instantly when weights change (no extra requests)', async () => {
    const user = userEvent.setup();
    const { fn } = mockApi({
      'GET /runs/5': runOf(THREE_MODELS.map((r) => r.model)),
      'GET /runs/5/summary': summary(THREE_MODELS),
      'GET /runs/5/results': { attempt_id: 1, results: [] },
      'GET /models': [],
    });
    renderApp(<ResultsPage />, { route: '/runs/5', path: '/runs/:id' });
    await screen.findByRole('table', { name: 'Model leaderboard' });
    const before = fn.mock.calls.length;
    expect(modelsInTable()[0]).toBe('alpha:1');

    // reasoning only: bravo (1.0) wins
    fireEvent.change(screen.getByLabelText('Classification'), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText('Generation'), { target: { value: '0' } });
    expect(modelsInTable()[0]).toBe('bravo:2');
    const top = within(screen.getByRole('table', { name: 'Model leaderboard' })).getAllByRole(
      'row',
    )[1];
    expect(within(top).getByText('100.0%')).toBeInTheDocument();
    expect(fn.mock.calls.length).toBe(before); // computed locally

    await user.click(screen.getByRole('button', { name: 'Reset to equal' }));
    expect(modelsInTable()[0]).toBe('alpha:1');
  });

  it('drops weights of categories that have no cases', async () => {
    const rows = [row('a:1', { cls: 1, gen: 0.5 }), row('b:1', { cls: 0.5, gen: 1 })];
    setup(rows, {}, { categories_present: ['classification', 'generation'] });
    await screen.findByRole('table', { name: 'Model leaderboard' });
    expect(screen.getByLabelText(/Reasoning/)).toBeDisabled();
    expect(screen.getByText('(no cases)')).toBeInTheDocument();
    expect(modelsInTable()).toEqual(['a:1', 'b:1']);
  });

  it('explains single-model runs and flags self-judged scores', async () => {
    setup([row('only:1', { cls: 1, rea: 1, gen: 0.8, latency: 1000, tps: 50, self: true })]);
    expect(await screen.findByText(/Only one model was evaluated/)).toBeInTheDocument();
    expect(screen.getAllByText('self-judged').length).toBeGreaterThan(0);
    expect(screen.getByText(/judged by a model that is also being evaluated/)).toBeInTheDocument();
  });

  it('shows unscored generation instead of 0 when there is no judge', async () => {
    setup([row('a:1', { cls: 1, rea: 1, gen: null, latency: 1000, tps: 50 })]);
    await screen.findByRole('table', { name: 'Model leaderboard' });
    expect(within(board()).getByText('unscored')).toBeInTheDocument();
    expect(screen.getByText('100.0%', { selector: 'strong' })).toBeInTheDocument(); // composite ignores it
  });

  it('offers CSV/JSON export and re-scoring', async () => {
    setup();
    expect(await screen.findByRole('link', { name: 'Export CSV' })).toHaveAttribute(
      'href',
      '/api/runs/5/export?format=csv',
    );
    expect(screen.getByRole('link', { name: 'Export JSON' })).toHaveAttribute(
      'href',
      '/api/runs/5/export?format=json',
    );
    expect(await screen.findByRole('button', { name: 'Re-score' })).toBeEnabled();
  });

  it('lets the user pick between scoring attempts, labelled by judging mode', async () => {
    setup(
      THREE_MODELS,
      {},
      {
        attempts: [
          {
            id: 1,
            judge_model: 'judge:1',
            judge_mode: 'single',
            created_at: '2026-01-01T00:00:00Z',
          },
          {
            id: 2,
            judge_model: null,
            judge_mode: 'cross_model',
            created_at: '2026-01-02T00:00:00Z',
          },
        ],
        attempt: { id: 2, judge_model: null, judge_mode: 'cross_model' },
      },
    );
    const sel = await screen.findByLabelText('Scoring attempt');
    expect(
      within(sel).getByRole('option', { name: '#2 · cross-model judging (latest)' }),
    ).toBeInTheDocument();
    expect(within(sel).getByRole('option', { name: '#1 · judge judge:1' })).toBeInTheDocument();
  });

  it('shows partial-results notices for cancelled and running runs', async () => {
    mockApi({
      'GET /runs/5': { ...runOf(['a:1']), status: 'cancelled' },
      'GET /runs/5/summary': summary([row('a:1', { cls: 1 })]),
      'GET /runs/5/results': {
        attempt_id: 1,
        results: [result('a:1', 1, 'classification', 'correct')],
      },
      'GET /models': [],
    });
    renderApp(<ResultsPage />, { route: '/runs/5', path: '/runs/:id' });
    expect(await screen.findByText(/run was cancelled; results are partial/)).toBeInTheDocument();
  });
});

const CROSS = {
  attempt: { id: 3, judge_model: null, judge_mode: 'cross_model' },
  attempts: [
    { id: 3, judge_model: null, judge_mode: 'cross_model', created_at: '2026-01-03T00:00:00Z' },
  ],
  judging: {
    mode: 'cross_model',
    judges: [
      { model: 'alpha:1', judged: 3, errors: 0, mean_score: 0.8, reasoning_mean_score: null },
      { model: 'bravo:2', judged: 3, errors: 1, mean_score: 0.35, reasoning_mean_score: 0.5 },
    ],
  },
};
const crossRows = () => THREE_MODELS.slice(0, 2).map((r) => ({ ...r, judges_per_answer: 1 }));

describe('cross-model judging results', () => {
  it('marks generation scores cross-judged and shows no self-judging warning', async () => {
    setup(crossRows(), {}, CROSS);
    await screen.findByRole('table', { name: 'Model leaderboard' });
    expect(within(board()).getAllByText('cross-judged · 1 judge')).toHaveLength(2);
    expect(within(board()).queryByText('self-judged')).toBeNull();
    expect(screen.queryByText(/judged by a model that is also being evaluated/)).toBeNull();
    expect(screen.getByText(/cross-model judging ·/)).toBeInTheDocument(); // header line names the mode
  });

  it('shows how many judges scored each answer', async () => {
    setup(
      crossRows().map((r) => ({ ...r, judges_per_answer: 2 })),
      {},
      CROSS,
    );
    await screen.findByRole('table', { name: 'Model leaderboard' });
    expect(within(board()).getAllByText('cross-judged · 2 judges')).toHaveLength(2);
  });

  it('lists every judge with its average score, failures and a fairness note', async () => {
    setup(crossRows(), {}, CROSS);
    const table = await screen.findByRole('table', { name: 'Judge strictness' });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(within(rows[0]).getByText('alpha:1')).toBeInTheDocument();
    expect(within(rows[0]).getByText('80.0%')).toBeInTheDocument();
    expect(within(rows[1]).getByText('35.0%')).toBeInTheDocument();
    expect(within(rows[1]).getByText('1 failed')).toBeInTheDocument();
    expect(
      within(table).getByRole('columnheader', { name: 'Average reasoning score' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/not perfectly like-for-like/)).toBeInTheDocument();
  });

  it('still flags self-judging for a single judge that is also a contestant, and points to cross-model', async () => {
    setup([
      row('only:1', { cls: 1, gen: 0.8, latency: 1, tps: 1, self: true }),
      row('other:2', { cls: 1, gen: 0.7, latency: 1, tps: 1 }),
    ]);
    expect(
      await screen.findByText(/judged by a model that is also being evaluated/),
    ).toBeInTheDocument();
    expect(screen.getByText(/re-scoring with cross-model judging/)).toBeInTheDocument();
    expect(within(board()).getAllByText('self-judged')).toHaveLength(1);
  });

  it('re-scores with cross-model judging (payload) and refreshes', async () => {
    const user = userEvent.setup();
    const { calls } = (() => {
      const api = mockApi({
        'GET /runs/5': runOf(['alpha:1', 'bravo:2']),
        'GET /runs/5/summary': summary(THREE_MODELS.slice(0, 2)),
        'GET /runs/5/results': { attempt_id: 1, results: [] },
        'GET /models': [],
        'POST /runs/5/rescore': { status: 'queued' },
      });
      renderApp(<ResultsPage />, { route: '/runs/5', path: '/runs/:id' });
      return api;
    })();
    await user.selectOptions(await screen.findByLabelText('Re-score with'), 'cross_model');
    expect(screen.queryByLabelText('Judge model')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Re-score' }));
    await waitFor(() => expect(calls.some((c) => c.path === '/runs/5/rescore')).toBe(true));
    expect(calls.find((c) => c.path === '/runs/5/rescore')!.body).toEqual({
      judge_mode: 'cross_model',
      judge_model: null,
    });
  });

  it('re-scores with a single judge only once one is chosen', async () => {
    const user = userEvent.setup();
    const { calls } = (() => {
      const api = mockApi({
        'GET /runs/5': runOf(['alpha:1', 'bravo:2']),
        'GET /runs/5/summary': summary(THREE_MODELS.slice(0, 2)),
        'GET /runs/5/results': { attempt_id: 1, results: [] },
        'GET /models': [
          {
            name: 'judge:1',
            digest: 'd',
            size_bytes: 1,
            parameter_size: '8B',
            quantization: 'Q4',
            family: 'f',
            capabilities: [],
            thinking: false,
          },
        ],
        'POST /runs/5/rescore': { status: 'queued' },
      });
      renderApp(<ResultsPage />, { route: '/runs/5', path: '/runs/:id' });
      return api;
    })();
    await user.selectOptions(await screen.findByLabelText('Re-score with'), 'single');
    expect(screen.getByRole('button', { name: 'Re-score' })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Judge model'), 'judge:1');
    await user.click(screen.getByRole('button', { name: 'Re-score' }));
    await waitFor(() => expect(calls.some((c) => c.path === '/runs/5/rescore')).toBe(true));
    expect(calls.find((c) => c.path === '/runs/5/rescore')!.body).toEqual({
      judge_mode: 'single',
      judge_model: 'judge:1',
    });
  });

  it('makes cross-model unavailable for a run with a single model, with the reason', async () => {
    setup([row('only:1', { cls: 1, gen: 0.8, latency: 1, tps: 1 })], {
      'GET /runs/5': runOf(['only:1']),
    });
    const select = await screen.findByLabelText('Re-score with');
    expect(within(select).getByRole('option', { name: 'Cross-model judging' })).toBeDisabled();
    expect(screen.getByText(/only one model/)).toBeInTheDocument();
    expect(select).toHaveAccessibleDescription(/only one model/);
  });
});
