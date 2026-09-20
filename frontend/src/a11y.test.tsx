import axe from 'axe-core';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { FakeEventSource } from './test/fakeEventSource';
import { result, row, runOf, summary, THREE_MODELS } from './test/fixtures';
import { baseRoutes, jsonError, mockApi, renderApp } from './test/utils';

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
