import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { jsonError, mockApi, renderApp, SUITE_DETAIL, SUITES } from '../test/utils';
import { runOf } from '../test/fixtures';
import HistoryPage from './HistoryPage';
import SuitesPage from './SuitesPage';

afterEach(() => vi.unstubAllGlobals());

const USER_SUITE = {
  id: 2,
  name: 'Mine',
  description: 'my cases',
  is_builtin: false,
  case_count: 1,
  counts_by_category: { classification: 1 },
};
const USER_DETAIL = {
  ...USER_SUITE,
  cases: [
    {
      id: 20,
      suite_id: 2,
      position: 0,
      category: 'classification',
      title: 'Tone',
      prompt: 'Great!',
      labels: ['positive', 'negative'],
      expected: 'positive',
    },
  ],
};

function suitesSetup(extra: Record<string, unknown> = {}) {
  const api = mockApi({
    'GET /suites': [...SUITES, USER_SUITE],
    'GET /suites/1': SUITE_DETAIL,
    'GET /suites/2': USER_DETAIL,
    ...extra,
  });
  renderApp(<SuitesPage />, { route: '/suites', path: '/suites' });
  return { ...api, user: userEvent.setup() };
}

describe('9.9 suites page', () => {
  it('shows the built-in suite as read-only but duplicable and exportable', async () => {
    const { user, calls } = suitesSetup({
      'POST /suites/1/duplicate': { ...USER_DETAIL, id: 3, name: 'Starter suite (copy)' },
      'GET /suites/3': { ...USER_DETAIL, id: 3 },
    });
    const suite = await screen.findByRole('region', { name: 'Suite Starter suite' });
    expect(within(suite).getByText('built-in · read-only')).toBeInTheDocument();
    expect(within(suite).queryByRole('button', { name: /Delete/ })).toBeNull();
    expect(within(suite).queryByRole('button', { name: 'Rename' })).toBeNull();
    expect(within(suite).queryByRole('button', { name: 'Add case' })).toBeNull();
    expect(within(suite).getByRole('link', { name: 'Export JSON' })).toHaveAttribute(
      'href',
      '/api/suites/1/export?format=json',
    );
    expect(within(suite).getByRole('link', { name: 'Export YAML' })).toHaveAttribute(
      'href',
      '/api/suites/1/export?format=yaml',
    );
    expect(within(suite).getByText('Bat and ball')).toBeInTheDocument();
    await user.click(within(suite).getByRole('button', { name: 'Duplicate' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path === '/suites/1/duplicate')).toBe(true),
    );
  });

  it('creates a suite and selects it', async () => {
    const { user, calls } = suitesSetup({
      'POST /suites': {
        id: 2,
        name: 'Fresh',
        description: '',
        is_builtin: false,
        case_count: 0,
        counts_by_category: {},
        cases: [],
      },
      'GET /suites/2': {
        id: 2,
        name: 'Fresh',
        description: '',
        is_builtin: false,
        case_count: 0,
        counts_by_category: {},
        cases: [],
      },
    });
    await screen.findByRole('region', { name: 'Suite Starter suite' });
    await user.type(screen.getByLabelText('New suite'), 'Fresh');
    await user.click(screen.getByRole('button', { name: 'Create' }));
    expect(calls.find((c) => c.method === 'POST' && c.path === '/suites')!.body).toEqual({
      name: 'Fresh',
    });
    expect(await screen.findByText('This suite has no cases yet')).toBeInTheDocument();
  });

  it('shows a name conflict from the server', async () => {
    const { user } = suitesSetup({
      'POST /suites': () => jsonError(409, "A suite named 'Mine' already exists"),
    });
    await screen.findByRole('region', { name: 'Suite Starter suite' });
    await user.type(screen.getByLabelText('New suite'), 'Mine');
    await user.click(screen.getByRole('button', { name: 'Create' }));
    expect(await screen.findByText(/already exists/)).toBeInTheDocument();
  });

  it('adds a case to an editable suite, validating first', async () => {
    const { user, calls } = suitesSetup({
      'POST /suites/2/cases': { ...USER_DETAIL.cases[0], id: 21 },
    });
    await user.click(await screen.findByRole('button', { name: /Mine/ }));
    const suite = await screen.findByRole('region', { name: 'Suite Mine' });
    await user.click(within(suite).getByRole('button', { name: 'Add case' }));
    await user.type(screen.getByLabelText('Prompt'), 'Awful service');
    await user.click(
      screen
        .getByRole('button', { name: 'Add case', description: '' })
        .closest('form')!
        .querySelector('button[type=submit]') as HTMLElement,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/at least two/);
    await user.type(screen.getByLabelText(/Allowed labels/), 'positive, negative');
    await user.type(screen.getByLabelText(/Expected answer/), 'negative');
    await user.click(
      screen
        .getByRole('form', { name: 'Test case' })
        .querySelector('button[type=submit]') as HTMLElement,
    );
    await waitFor(() => expect(calls.some((c) => c.path === '/suites/2/cases')).toBe(true));
    expect(calls.find((c) => c.path === '/suites/2/cases')!.body).toMatchObject({
      category: 'classification',
      prompt: 'Awful service',
      labels: ['positive', 'negative'],
      expected: 'negative',
    });
  });

  it('builds generation cases with constraints and a rubric', async () => {
    const { user, calls } = suitesSetup({
      'POST /suites/2/cases': { ...USER_DETAIL.cases[0], id: 22 },
    });
    await user.click(await screen.findByRole('button', { name: /Mine/ }));
    await user.click(await screen.findByRole('button', { name: 'Add case' }));
    await user.selectOptions(screen.getByLabelText('Category'), 'generation');
    await user.type(screen.getByLabelText('Prompt'), 'Write a haiku');
    await user.type(screen.getByLabelText('Max words'), '30');
    await user.type(screen.getByLabelText(/Required keywords/), 'rain, sky');
    await user.type(screen.getByLabelText(/Judge rubric/), 'Imagery: vivid\nForm');
    await user.click(
      screen
        .getByRole('form', { name: 'Test case' })
        .querySelector('button[type=submit]') as HTMLElement,
    );
    await waitFor(() => expect(calls.some((c) => c.path === '/suites/2/cases')).toBe(true));
    expect(calls.find((c) => c.path === '/suites/2/cases')!.body).toMatchObject({
      category: 'generation',
      constraints: { max_words: 30, required_keywords: ['rain', 'sky'], forbidden_keywords: [] },
      rubric: [{ name: 'Imagery', description: 'vivid' }, { name: 'Form' }],
    });
  });

  it('edits and deletes cases and deletes the suite after confirmation', async () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    );
    const { user, calls } = suitesSetup({
      'PUT /cases/20': USER_DETAIL.cases[0],
      'DELETE /cases/20': new Response(null, { status: 204 }),
      'DELETE /suites/2': new Response(null, { status: 204 }),
    });
    await user.click(await screen.findByRole('button', { name: /Mine/ }));
    const suite = await screen.findByRole('region', { name: 'Suite Mine' });
    await user.click(within(suite).getByRole('button', { name: 'Edit case Tone' }));
    expect(screen.getByLabelText('Prompt')).toHaveValue('Great!');
    await user.clear(screen.getByLabelText('Prompt'));
    await user.type(screen.getByLabelText('Prompt'), 'Fantastic!');
    await user.click(screen.getByRole('button', { name: 'Save case' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
    expect(calls.find((c) => c.method === 'PUT')!.body.prompt).toBe('Fantastic!');

    await user.click(within(suite).getByRole('button', { name: 'Delete case Tone' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path === '/cases/20')).toBe(true),
    );
    await user.click(within(suite).getByRole('button', { name: 'Delete suite Mine' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path === '/suites/2')).toBe(true),
    );
  });

  it('imports a suite and lists per-field errors when the file is invalid', async () => {
    const { user } = suitesSetup({
      'POST /suites/import': ({ body }: { body: { content: string } }) =>
        body.content.includes('bad')
          ? jsonError(422, {
              code: 'invalid_suite_file',
              errors: [
                { field: 'cases[1].prompt', message: 'prompt must not be empty' },
                { field: 'cases[2]', message: 'expected label must be one of the allowed labels' },
              ],
            })
          : { ...USER_DETAIL, id: 2 },
    });
    await screen.findByRole('region', { name: 'Suite Starter suite' });
    await user.click(screen.getByRole('button', { name: 'Import…' }));
    await user.click(screen.getByLabelText(/paste it here/));
    await user.paste('{"name":"bad"}');
    await user.click(screen.getByRole('button', { name: 'Import suite' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('nothing was created');
    expect(alert).toHaveTextContent('cases[1].prompt: prompt must not be empty');
    expect(alert).toHaveTextContent('cases[2]: expected label must be one of the allowed labels');
  });
});

// ---------------------------------------------------------------- history
const runRow = (id: number, extra: Record<string, unknown> = {}) => ({
  ...runOf(['a:1', 'b:1']),
  id,
  name: `Run ${id}`,
  cases: undefined,
  ...extra,
});

function historySetup(runs: unknown[], extra: Record<string, unknown> = {}) {
  const api = mockApi({ 'GET /runs': runs, ...extra });
  renderApp(<HistoryPage />, { route: '/history', path: '/history' });
  return { ...api, user: userEvent.setup() };
}

describe('9.9 history page', () => {
  it('shows an empty state when there are no runs', async () => {
    historySetup([]);
    expect(await screen.findByText('No runs yet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Set up your first run' })).toHaveAttribute(
      'href',
      '/',
    );
  });

  it('lists runs with status, models, links and re-run lineage', async () => {
    historySetup([
      runRow(3, { parent_run_id: 1 }),
      runRow(2, { status: 'running', finished_at: null, progress: { completed: 2, total: 8 } }),
      runRow(1, { status: 'failed' }),
    ]);
    const table = await screen.findByRole('table', { name: 'Runs' });
    expect(within(table).getAllByRole('row')).toHaveLength(4);
    expect(within(table).getByRole('link', { name: '#3 Run 3' })).toHaveAttribute(
      'href',
      '/runs/3',
    );
    expect(within(table).getByRole('link', { name: '#2 Run 2' })).toHaveAttribute(
      'href',
      '/runs/2/live',
    ); // active -> live view
    expect(within(table).getByText('re-run of #1')).toBeInTheDocument();
    expect(within(table).getByText('2/8')).toBeInTheDocument();
    expect(within(table).getAllByText('a:1, b:1')).toHaveLength(3);
    const active = within(table).getAllByRole('row')[2];
    expect(within(active).getByRole('button', { name: 'Re-run' })).toBeDisabled();
    expect(within(active).getByRole('button', { name: 'Delete' })).toBeDisabled();
  });

  it('re-runs a past run and opens its live view', async () => {
    const { user, calls } = historySetup([runRow(1)], { 'POST /runs/1/rerun': { id: 9 } });
    await user.click(await screen.findByRole('button', { name: 'Re-run' }));
    expect(await screen.findByText('LIVE PAGE')).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST' && c.path === '/runs/1/rerun')).toBe(true);
  });

  it('deletes only after confirmation', async () => {
    const confirm = vi.fn(() => false);
    vi.stubGlobal('confirm', confirm);
    const { user, calls } = historySetup([runRow(1)], {
      'DELETE /runs/1': new Response(null, { status: 204 }),
    });
    await user.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
    confirm.mockReturnValue(true);
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path === '/runs/1')).toBe(true),
    );
  });

  it('compares two selected runs and shows direction with arrows and words, not colour', async () => {
    const compare = {
      a: { id: 1, name: 'Before', status: 'completed' },
      b: { id: 2, name: 'After', status: 'completed' },
      models: [
        {
          model: 'a:1',
          same_digest: false,
          composite: { a: 0.5, b: 0.75, delta: 0.25 },
          categories: {
            reasoning: { a: 0, b: 1, delta: 1 },
            classification: { a: 1, b: 1, delta: 0 },
            generation: { a: 0.9, b: 0.8, delta: -0.1 },
          },
          performance: {
            latency_ms: { a: 6000, b: 4000, delta: -2000 },
            ttft_ms: { a: 300, b: 300, delta: 0 },
            tokens_per_s: { a: 40, b: 44, delta: 4 },
          },
        },
      ],
      only_in_a: ['b:1'],
      only_in_b: ['c:1'],
      cases: [{ model: 'a:1', category: 'reasoning', title: 'Bat and ball', a: 0, b: 1, delta: 1 }],
    };
    const { user, calls } = historySetup([runRow(2), runRow(1)], {
      'GET /runs/compare?a=1&b=2': compare,
    });
    const go = await screen.findByRole('button', { name: /Compare selected \(0\/2\)/ });
    expect(go).toBeDisabled();
    await user.click(await screen.findByRole('checkbox', { name: 'Select run 2 for comparison' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select run 1 for comparison' }));
    await user.click(screen.getByRole('button', { name: /Compare selected \(2\/2\)/ }));
    const table = await screen.findByRole('table', { name: 'Model changes' });
    expect(calls.some((c) => c.path === '/runs/compare?a=1&b=2')).toBe(true);
    expect(within(table).getByText(/▲ \+25\.0 pts/)).toBeInTheDocument(); // composite
    expect(within(table).getByText(/▲ \+100\.0 pts/)).toBeInTheDocument(); // reasoning
    expect(within(table).getByText(/▼ −10\.0 pts/)).toBeInTheDocument(); // generation
    expect(within(table).getByText(/▼ −2\.00 s/)).toBeInTheDocument(); // latency
    expect(within(table).getByText('＝ no change')).toBeInTheDocument();
    expect(within(table).getByText('different build')).toBeInTheDocument();
    expect(screen.getByText(/Only in run #1: b:1/)).toBeInTheDocument();
    expect(screen.getByText(/Only in run #2: c:1/)).toBeInTheDocument();
  });

  it('keeps at most two runs selected', async () => {
    const { user } = historySetup([runRow(3), runRow(2), runRow(1)]);
    for (const id of [1, 2, 3])
      await user.click(
        await screen.findByRole('checkbox', { name: `Select run ${id} for comparison` }),
      );
    expect(screen.getByRole('checkbox', { name: 'Select run 1 for comparison' })).not.toBeChecked();
    expect(screen.getByRole('button', { name: /Compare selected \(2\/2\)/ })).toBeEnabled();
  });
});
