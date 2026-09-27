import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  baseRoutes,
  CLOUD_MODELS,
  HEALTH_OK,
  jsonError,
  MODELS,
  mockApi,
  renderApp,
} from '../test/utils';
import RunSetupPage from './RunSetupPage';

const setup = (routes: Record<string, unknown> = {}) => {
  const api = mockApi({ ...baseRoutes, ...routes });
  renderApp(<RunSetupPage />);
  return { ...api, user: userEvent.setup() };
};
const startButton = () => screen.getByRole('button', { name: /start evaluation/i });
const model = (name: string) => screen.findByRole('checkbox', { name });

describe('9.2 model selection', () => {
  it('lists installed models with details and a thinking flag', async () => {
    setup();
    await model('qwen3:8b');
    const card = screen
      .getByRole('checkbox', { name: 'qwen3:8b' })
      .closest('.model-card') as HTMLElement;
    expect(within(card).getByText(/8\.2B · Q4_K_M · qwen3/)).toBeInTheDocument();
    expect(within(card).getByText('thinking')).toBeInTheDocument();
    const plain = screen
      .getByRole('checkbox', { name: 'llama3:8b' })
      .closest('.model-card') as HTMLElement;
    expect(within(plain).queryByText('thinking')).toBeNull();
  });

  it('shows the selected count and enables starting once models and cases are chosen', async () => {
    const { user } = setup();
    await user.click(await model('gemma4:e4b'));
    await user.click(screen.getByRole('checkbox', { name: 'llama3:8b' }));
    await user.click(screen.getByRole('checkbox', { name: 'qwen3:8b' }));
    expect(screen.getByText('3 selected')).toBeInTheDocument();
    expect(startButton()).toBeDisabled(); // no cases yet
    expect(screen.getByText('Select a test suite or add an ad-hoc prompt.')).toBeInTheDocument();
    await user.click(await screen.findByRole('checkbox', { name: 'Starter suite' }));
    await waitFor(() => expect(startButton()).toBeEnabled());
    expect(screen.getByText('9', { selector: 'strong' })).toBeInTheDocument(); // 3 models x 3 cases
  });

  it('select all / clear', async () => {
    const { user } = setup();
    await model('gemma4:e4b');
    await user.click(screen.getByRole('button', { name: 'Select all' }));
    expect(screen.getByText('3 selected')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.getByText('0 selected')).toBeInTheDocument();
  });

  it('shows the Ollama-unreachable state and blocks starting', async () => {
    const { user } = setup({
      'GET /health': {
        ...HEALTH_OK,
        status: 'ollama_unreachable',
        ollama: { ...HEALTH_OK.ollama, reachable: false, error: 'refused' },
      },
      'GET /models': () =>
        jsonError(503, {
          code: 'ollama_unreachable',
          message: 'Cannot reach Ollama',
          base_url: 'http://localhost:11434',
        }),
    });
    expect(
      await screen.findByText('Ollama unreachable', { selector: 'strong' }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/Cannot reach Ollama/)).toBeInTheDocument();
    expect(screen.getByText(/ollama serve/)).toBeInTheDocument();
    await user.click(
      await screen.findByRole('checkbox', { name: 'Starter suite' }).catch(() => document.body),
    );
    expect(startButton()).toBeDisabled();
  });

  it('shows an empty state when no models are installed', async () => {
    setup({ 'GET /models': [] });
    expect(await screen.findByText('No models available')).toBeInTheDocument();
    expect(screen.getByText(/ollama pull/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Providers' })).toHaveAttribute('href', '/providers');
  });

  it('refresh re-reads models and drops selections that disappeared', async () => {
    const { user, calls } = setup({
      'GET /models?refresh=1': MODELS.filter((m) => m.name !== 'llama3:8b'),
    });
    await user.click(await model('llama3:8b'));
    await user.click(screen.getByRole('checkbox', { name: 'qwen3:8b' }));
    expect(screen.getByText('2 selected')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(screen.queryByRole('checkbox', { name: 'llama3:8b' })).toBeNull());
    expect(calls.some((c) => c.path === '/models?refresh=1')).toBe(true);
    expect(screen.getByText('1 selected')).toBeInTheDocument();
  });
});

describe('9.3 input entry', () => {
  const openAdhoc = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole('tab', { name: /ad-hoc prompt/i }));
  };

  it('validates the ad-hoc form', async () => {
    const { user } = setup();
    await openAdhoc(user);
    const add = () => user.click(screen.getByRole('button', { name: 'Add prompt to run' }));
    await add();
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a prompt.');

    await user.type(screen.getByLabelText('Prompt'), 'I love it');
    await user.type(screen.getByLabelText(/Labels/), 'positive');
    await add();
    expect(screen.getByRole('alert')).toHaveTextContent(/at least two/);

    await user.clear(screen.getByLabelText(/Labels/));
    await user.type(screen.getByLabelText(/Labels/), 'positive, negative');
    await user.type(screen.getByLabelText(/Expected answer/), 'neutral');
    await add();
    expect(screen.getByRole('alert')).toHaveTextContent(/expected label must be one of/);

    await user.selectOptions(screen.getByLabelText('Category'), 'reasoning');
    await user.clear(screen.getByLabelText(/Expected answer/));
    await user.type(screen.getByLabelText(/Expected answer/), 'abc');
    await add();
    expect(screen.getByRole('alert')).toHaveTextContent(/numeric expected answer/);
  });

  it('submits an ad-hoc classification prompt with its expected answer', async () => {
    const { user, calls } = setup({ 'POST /runs': { id: 42 } });
    await user.click(await model('qwen3:8b'));
    await openAdhoc(user);
    await user.type(screen.getByLabelText('Prompt'), 'I love it');
    await user.type(screen.getByLabelText(/Labels/), 'positive, negative');
    await user.type(screen.getByLabelText(/Expected answer/), 'positive');
    await user.click(screen.getByRole('button', { name: 'Add prompt to run' }));
    expect(screen.getByText(/I love it/, { selector: 'li' })).toBeInTheDocument();
    await user.click(startButton());
    expect(await screen.findByText('LIVE PAGE')).toBeInTheDocument();

    const body = calls.find((c) => c.method === 'POST' && c.path === '/runs')!.body;
    expect(body).toMatchObject({
      models: ['qwen3:8b'],
      suite_ids: [],
      exclude_case_ids: [],
      judge_model: null,
      adhoc_cases: [
        {
          category: 'classification',
          prompt: 'I love it',
          labels: ['positive', 'negative'],
          expected: 'positive',
          system_prompt: null,
        },
      ],
    });
  });

  it('submits an ad-hoc prompt without an expected answer', async () => {
    const { user, calls } = setup({ 'POST /runs': { id: 1 } });
    await user.click(await model('qwen3:8b'));
    await openAdhoc(user);
    await user.selectOptions(screen.getByLabelText('Category'), 'generation');
    await user.type(screen.getByLabelText('Prompt'), 'Write a haiku');
    await user.click(screen.getByRole('button', { name: 'Add prompt to run' }));
    await user.click(startButton());
    await screen.findByText('LIVE PAGE');
    const c = calls.find((x) => x.path === '/runs')!.body.adhoc_cases[0];
    expect(c).toMatchObject({ category: 'generation', prompt: 'Write a haiku', expected: null });
  });

  it('lets the user deselect individual cases of a chosen suite', async () => {
    const { user, calls } = setup({ 'POST /runs': { id: 1 } });
    await user.click(await model('qwen3:8b'));
    await user.click(await screen.findByRole('checkbox', { name: 'Starter suite' }));
    expect(await screen.findByText('3 of 3 cases', { exact: false })).toBeInTheDocument();
    await user.click(await screen.findByRole('checkbox', { name: /Bat and ball/ }));
    expect(screen.getByText('2 of 3 cases', { exact: false })).toBeInTheDocument();
    await user.click(startButton());
    await screen.findByText('LIVE PAGE');
    expect(calls.find((x) => x.path === '/runs')!.body).toMatchObject({
      suite_ids: [1],
      exclude_case_ids: [11],
    });
  });

  it('removes an ad-hoc prompt from the run', async () => {
    const { user } = setup();
    await openAdhoc(user);
    await user.type(screen.getByLabelText('Prompt'), 'temp');
    await user.selectOptions(screen.getByLabelText('Category'), 'generation');
    await user.click(screen.getByRole('button', { name: 'Add prompt to run' }));
    await user.click(screen.getByRole('button', { name: 'Remove' }));
    expect(screen.getByText('None yet.')).toBeInTheDocument();
  });

  it('shows server-side errors from starting the run', async () => {
    const { user } = setup({
      'POST /runs': () =>
        jsonError(422, {
          code: 'model_not_installed',
          message: 'Not installed in Ollama: qwen3:8b',
        }),
    });
    await user.click(await model('qwen3:8b'));
    await user.click(await screen.findByRole('checkbox', { name: 'Starter suite' }));
    await user.click(startButton());
    expect(await screen.findByText(/Not installed in Ollama/)).toBeInTheDocument();
  });
});

describe('9.4 run configuration', () => {
  it('starts with reproducible defaults', async () => {
    setup();
    await model('qwen3:8b');
    expect(screen.getByLabelText('Temperature')).toHaveValue(0);
    expect(screen.getByLabelText('Seed')).toHaveValue(42);
    expect(screen.getByLabelText('Repeats')).toHaveValue(1);
    expect(screen.getByLabelText('Context size')).toHaveValue(8192);
    expect(screen.getByLabelText('Max output tokens')).toHaveValue(4096);
    expect(screen.getByRole('checkbox', { name: /Enable thinking/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Warm up each model/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'No judge' })).toBeChecked();
    expect(screen.queryByLabelText('Judge model')).toBeNull(); // only shown for a single judge
  });

  it('sends changed settings and the judge model', async () => {
    const { user, calls } = setup({ 'POST /runs': { id: 1 } });
    await user.click(await model('qwen3:8b'));
    await user.click(await screen.findByRole('checkbox', { name: 'Starter suite' }));
    await user.clear(screen.getByLabelText('Repeats'));
    await user.type(screen.getByLabelText('Repeats'), '3');
    await user.click(screen.getByRole('checkbox', { name: /Warm up each model/ }));
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    await user.selectOptions(screen.getByLabelText('Judge model'), 'gemma4:e4b');
    await user.click(startButton());
    await screen.findByText('LIVE PAGE');
    const body = calls.find((x) => x.path === '/runs')!.body;
    expect(body.judge_model).toBe('gemma4:e4b');
    expect(body.judge_mode).toBe('single');
    expect(body.config).toMatchObject({
      repeats: 3,
      warmup: false,
      temperature: 0,
      seed: 42,
      think: true,
    });
  });

  it('warns about self-judging when the judge is one of the evaluated models', async () => {
    const { user } = setup();
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    await user.selectOptions(screen.getByLabelText('Judge model'), 'qwen3:8b');
    expect(
      screen.getByText(/both judge and one of the models being evaluated/),
    ).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Judge model'), 'gemma4:e4b');
    expect(screen.queryByText(/both judge and one of the models/)).toBeNull();
  });

  it('explains what happens without a judge when generation cases are selected', async () => {
    const { user } = setup();
    await model('qwen3:8b');
    expect(screen.queryByText(/No judge selected/)).toBeNull();
    await user.click(await screen.findByRole('checkbox', { name: 'Starter suite' }));
    expect(screen.getByText(/No judge selected/)).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    expect(screen.queryByText(/No judge selected/)).toBeNull();
  });
});

describe('number fields', () => {
  it('can be cleared and retyped without snapping to the minimum', async () => {
    const { user } = setup();
    await model('qwen3:8b');
    const repeats = screen.getByLabelText('Repeats');
    await user.clear(repeats);
    expect(repeats).toHaveValue(null); // empty while typing
    await user.type(repeats, '5');
    expect(repeats).toHaveValue(5);
  });

  it('clamps out-of-range values when focus leaves and restores empty input', async () => {
    const { user } = setup();
    await model('qwen3:8b');
    const repeats = screen.getByLabelText('Repeats');
    await user.clear(repeats);
    await user.type(repeats, '99');
    await user.tab();
    expect(repeats).toHaveValue(20);
    await user.clear(repeats);
    await user.tab();
    expect(repeats).toHaveValue(20); // empty -> previous valid value
  });
});

describe('save ad-hoc prompt to a suite', () => {
  it('saves a prompt into a new suite', async () => {
    const { user, calls } = setup({
      'GET /suites': [
        {
          id: 1,
          name: 'Starter suite',
          description: '',
          is_builtin: true,
          case_count: 3,
          counts_by_category: {},
        },
      ],
      'POST /suites/save-adhoc': { id: 5 },
    });
    await user.click(await screen.findByRole('tab', { name: /ad-hoc prompt/i }));
    await user.selectOptions(screen.getByLabelText('Category'), 'generation');
    await user.type(screen.getByLabelText('Prompt'), 'Write a limerick');
    await user.click(screen.getByRole('button', { name: 'Add prompt to run' }));
    await user.click(screen.getByRole('button', { name: 'Save to suite…' }));
    const target = screen.getByLabelText('Target suite');
    expect(within(target).queryByRole('option', { name: 'Starter suite' })).toBeNull(); // built-in is read-only
    await user.type(screen.getByLabelText('New suite name'), 'Limericks');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('saved')).toBeInTheDocument();
    expect(calls.find((c) => c.path === '/suites/save-adhoc')!.body).toMatchObject({
      new_suite_name: 'Limericks',
      case: { category: 'generation', prompt: 'Write a limerick' },
    });
  });
});

describe('cross-model judging option', () => {
  const pickSuite = async (user: ReturnType<typeof userEvent.setup>) =>
    user.click(await screen.findByRole('checkbox', { name: 'Starter suite' }));
  const posted = (calls: ReturnType<typeof mockApi>['calls']) =>
    calls.find((c) => c.method === 'POST' && c.path === '/runs')!.body;

  it('offers three judging modes with an explanation for each', async () => {
    setup();
    await model('qwen3:8b');
    const group = screen.getByRole('radiogroup', { name: 'Judging mode' });
    expect(
      within(group)
        .getAllByRole('radio')
        .map((r) => r.getAttribute('value')),
    ).toEqual(['none', 'single', 'cross_model']);
    expect(within(group).getByText(/One model scores every answer/)).toBeInTheDocument();
    expect(within(group).getByText(/no model grades itself/)).toBeInTheDocument();
  });

  it('sends the right payload for each mode', async () => {
    const { user, calls } = setup({ 'POST /runs': { id: 1 } });
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: 'gemma4:e4b' }));
    await pickSuite(user);

    await user.click(startButton()); // default: none
    await screen.findByText('LIVE PAGE');
    expect(posted(calls)).toMatchObject({ judge_mode: 'none', judge_model: null });
  });

  it.each([
    ['single', 'Single judge model', { judge_mode: 'single', judge_model: 'llama3:8b' }],
    ['cross_model', 'Cross-model judging', { judge_mode: 'cross_model', judge_model: null }],
  ])('sends %s', async (_mode, label, expected) => {
    const { user, calls } = setup({ 'POST /runs': { id: 1 } });
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: 'gemma4:e4b' }));
    await pickSuite(user);
    await user.click(screen.getByRole('radio', { name: label }));
    if (label === 'Single judge model')
      await user.selectOptions(screen.getByLabelText('Judge model'), 'llama3:8b');
    await user.click(startButton());
    await screen.findByText('LIVE PAGE');
    expect(posted(calls)).toMatchObject(expected);
  });

  it('a single judge must be chosen before starting', async () => {
    const { user } = setup();
    await user.click(await model('qwen3:8b'));
    await pickSuite(user);
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    expect(startButton()).toBeDisabled();
    expect(
      screen.getByText(/Choose a judge model, or pick another judging mode/),
    ).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Judge model'), 'llama3:8b');
    expect(startButton()).toBeEnabled();
  });

  it('disables cross-model with an explanation until two models are selected', async () => {
    const { user } = setup();
    const cross = () => screen.getByRole('radio', { name: 'Cross-model judging' });
    await model('qwen3:8b');
    expect(cross()).toBeDisabled();
    expect(cross()).toHaveAccessibleDescription(/Needs at least two selected models/);
    await user.click(screen.getByRole('checkbox', { name: 'qwen3:8b' }));
    expect(cross()).toBeDisabled(); // still only one
    await user.click(screen.getByRole('checkbox', { name: 'gemma4:e4b' }));
    expect(cross()).toBeEnabled();
  });

  it('hides the single judge picker and explains the trade-off with a cost estimate', async () => {
    const { user } = setup();
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: 'gemma4:e4b' }));
    await user.click(screen.getByRole('checkbox', { name: 'llama3:8b' }));
    await pickSuite(user); // starter suite: 1 generation case
    await user.click(screen.getByRole('radio', { name: 'Cross-model judging' }));
    expect(screen.queryByLabelText('Judge model')).toBeNull();
    expect(screen.getByText(/Models never grade themselves/)).toBeInTheDocument();
    expect(screen.getByText(/differ in strictness/)).toBeInTheDocument();
    expect(screen.getByTestId('judge-estimate')).toHaveTextContent(
      'About 6 judgements (3 answers × 2 other models)',
    );
    // reasoning-quality judging adds the reasoning case
    await user.click(
      screen.getByRole('checkbox', { name: /judge the quality of reasoning traces/ }),
    );
    expect(screen.getByTestId('judge-estimate')).toHaveTextContent(
      'About 12 judgements (6 answers × 2 other models)',
    );
    expect(startButton()).toBeEnabled(); // no judge model needed
  });

  it('switches back to no judge, with a message, if the selection drops below two models', async () => {
    const { user } = setup();
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: 'gemma4:e4b' }));
    await user.click(screen.getByRole('radio', { name: 'Cross-model judging' }));
    await user.click(screen.getByRole('checkbox', { name: 'gemma4:e4b' })); // now one model
    expect(screen.getByRole('radio', { name: 'No judge' })).toBeChecked();
    expect(
      screen.getByText(/Cross-model judging was switched off because it needs at least two models/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByText(/switched off/)).toBeNull();
  });

  it('reasoning-quality judging is only available with a judge', async () => {
    const { user } = setup();
    await model('qwen3:8b');
    const box = () =>
      screen.getByRole('checkbox', { name: /judge the quality of reasoning traces/ });
    expect(box()).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    expect(box()).toBeEnabled();
  });

  it('offers to switch a self-judging setup to cross-model judging', async () => {
    const { user } = setup();
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: 'gemma4:e4b' }));
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    await user.selectOptions(screen.getByLabelText('Judge model'), 'qwen3:8b');
    expect(
      screen.getByText(/both judge and one of the models being evaluated/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Use cross-model judging instead' }));
    expect(screen.getByRole('radio', { name: 'Cross-model judging' })).toBeChecked();
    expect(screen.queryByLabelText('Judge model')).toBeNull(); // single judge selection cleared
    expect(screen.queryByText(/both judge and one of the models/)).toBeNull();
  });

  it('cannot offer the switch when only one model is selected', async () => {
    const { user } = setup();
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    await user.selectOptions(screen.getByLabelText('Judge model'), 'qwen3:8b');
    expect(
      screen.getByText(/both judge and one of the models being evaluated/),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Use cross-model judging instead' })).toBeNull();
  });
});

describe('6.3 enterprise models in the picker', () => {
  const MIXED = [...MODELS, ...CLOUD_MODELS];
  const down = {
    ...HEALTH_OK,
    status: 'ollama_unreachable',
    ollama: { ...HEALTH_OK.ollama, reachable: false, error: 'refused' },
  };

  it('groups models by source: Local (Ollama) and one group per provider', async () => {
    setup({ 'GET /models': MIXED });
    await model('@oa/gpt-4o');
    const picker = screen.getByRole('group', { name: 'Available models' });
    const groups = within(picker)
      .getAllByRole('group')
      .filter((g) => g.tagName === 'FIELDSET');
    expect(groups.map((g) => g.querySelector('legend')?.textContent)).toEqual([
      'Local (Ollama)',
      'an (Anthropic)',
      'oa (OpenAI)',
    ]);
    const oa = within(groups[2]);
    expect(oa.getByRole('checkbox', { name: '@oa/gpt-4o' })).toBeInTheDocument();
    expect(oa.getByRole('checkbox', { name: '@oa/o3' })).toBeInTheDocument();
    expect(within(groups[0]).getByRole('checkbox', { name: 'qwen3:8b' })).toBeInTheDocument();
  });

  it('marks enterprise models with a cloud badge, provider kind and reasoning flag', async () => {
    setup({ 'GET /models': MIXED });
    const o3Card = (await model('@oa/o3')).closest('.model-card') as HTMLElement;
    expect(within(o3Card).getByText('cloud')).toBeInTheDocument();
    expect(within(o3Card).getByText('OpenAI')).toBeInTheDocument();
    expect(within(o3Card).getByText('reasoning')).toBeInTheDocument();

    const gptCard = screen
      .getByRole('checkbox', { name: '@oa/gpt-4o' })
      .closest('.model-card') as HTMLElement;
    expect(within(gptCard).getByText('GPT-4o')).toBeInTheDocument(); // display_name shown for cloud models

    const local = screen
      .getByRole('checkbox', { name: 'qwen3:8b' })
      .closest('.model-card') as HTMLElement;
    expect(within(local).queryByText('cloud')).toBeNull();
    expect(within(local).getByText('thinking')).toBeInTheDocument();
  });

  it('shows a model without a key as disabled and names the missing variable', async () => {
    const { user } = setup({ 'GET /models': MIXED });
    const claude = await model('@an/claude');
    expect(claude).toBeDisabled();
    expect(claude).toHaveAccessibleDescription(/environment variable AN_KEY is empty/);
    const card = claude.closest('.model-card') as HTMLElement;
    expect(within(card).getByText('unavailable')).toBeInTheDocument();
    await user.click(claude);
    expect(screen.getByText('0 selected')).toBeInTheDocument();
  });

  it('“Select all” picks only models that are available', async () => {
    const { user } = setup({ 'GET /models': MIXED });
    await model('@oa/gpt-4o');
    await user.click(screen.getByRole('button', { name: 'Select all' }));
    expect(screen.getByText('5 selected')).toBeInTheDocument(); // 3 local + gpt-4o + o3, not the key-less claude
    expect(screen.getByRole('checkbox', { name: '@an/claude' })).not.toBeChecked();
  });

  it('keeps enterprise models selectable and startable while Ollama is down', async () => {
    const { user } = setup({ 'GET /health': down, 'GET /models': CLOUD_MODELS });
    expect(await screen.findByText(/local models are unavailable/)).toBeInTheDocument();
    expect(screen.queryByText('Local (Ollama)')).toBeNull();
    await user.click(await model('@oa/gpt-4o'));
    await user.click(await screen.findByRole('checkbox', { name: 'Starter suite' }));
    await waitFor(() => expect(startButton()).toBeEnabled());
    expect(screen.queryByText(/Ollama is unreachable, and this run uses a local model/)).toBeNull();
  });

  it('still blocks a run that includes a local model while Ollama is down', async () => {
    const { user } = setup({ 'GET /health': down, 'GET /models': MIXED });
    await user.click(await model('qwen3:8b'));
    await user.click(await model('@oa/gpt-4o'));
    await user.click(await screen.findByRole('checkbox', { name: 'Starter suite' }));
    expect(startButton()).toBeDisabled();
    expect(
      screen.getByText('Ollama is unreachable, and this run uses a local model.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'qwen3:8b' }));
    expect(startButton()).toBeEnabled();
  });

  it('sends enterprise model references unchanged in the run request', async () => {
    const { user, calls } = setup({ 'GET /models': MIXED, 'POST /runs': { id: 1 } });
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: '@oa/o3' }));
    await user.click(await screen.findByRole('checkbox', { name: 'Starter suite' }));
    await user.click(startButton());
    await screen.findByText('LIVE PAGE');
    expect(calls.find((c) => c.path === '/runs')!.body.models).toEqual(['qwen3:8b', '@oa/o3']);
  });

  it('drops a selected model that disappears after a refresh', async () => {
    const { user } = setup({
      'GET /models': MIXED,
      'GET /models?refresh=1': MIXED.filter((m) => m.name !== '@oa/o3'),
    });
    await user.click(await model('@oa/o3'));
    await user.click(screen.getByRole('checkbox', { name: '@oa/gpt-4o' }));
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(screen.queryByRole('checkbox', { name: '@oa/o3' })).toBeNull());
    expect(screen.getByText('1 selected')).toBeInTheDocument();
  });

  it('explains both ways to add models when nothing is available', async () => {
    setup({ 'GET /models': [] });
    expect(await screen.findByText('No models available')).toBeInTheDocument();
    expect(screen.getByText(/ollama pull/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Providers' })).toBeInTheDocument();
  });
});

describe('6.4 judging across local and enterprise models', () => {
  const MIXED = [...MODELS, ...CLOUD_MODELS]; // gemma4:e4b, llama3:8b, qwen3:8b (local); @oa/gpt-4o, @oa/o3 (available), @an/claude (no key)

  const pickSuite = async (user: ReturnType<typeof userEvent.setup>) =>
    user.click(await screen.findByRole('checkbox', { name: 'Starter suite' }));

  it('offers every available model as judge, labelled with its provider, and excludes unavailable ones', async () => {
    const { user } = setup({ 'GET /models': MIXED });
    await model('qwen3:8b');
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    const select = screen.getByLabelText('Judge model');
    const optionLabels = within(select)
      .getAllByRole('option')
      .map((o) => o.textContent);
    expect(optionLabels).toContain('qwen3:8b');
    expect(optionLabels).toContain('GPT-4o (oa)');
    expect(optionLabels).toContain('o3 (oa)');
    expect(optionLabels).not.toContain('claude (an)'); // @an/claude has no key: not offered as judge
  });

  it('shows no data-sharing notice for a local-only run', async () => {
    const { user } = setup({ 'GET /models': MIXED });
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: 'llama3:8b' }));
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    await user.selectOptions(screen.getByLabelText('Judge model'), 'llama3:8b');
    expect(screen.queryByText(/This run will send data to/)).toBeNull();
  });

  it('discloses the provider when an enterprise model is a contestant', async () => {
    const { user } = setup({ 'GET /models': MIXED });
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: '@oa/gpt-4o' }));
    expect(await screen.findByText(/This run will send data to/)).toBeInTheDocument();
    expect(screen.getByText(/oa \(OpenAI\) — as contestant/)).toBeInTheDocument();
  });

  it('discloses the provider when it is chosen as the single judge, even if not a contestant', async () => {
    const { user } = setup({ 'GET /models': MIXED });
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: 'llama3:8b' }));
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    await user.selectOptions(screen.getByLabelText('Judge model'), '@oa/gpt-4o');
    expect(await screen.findByText(/oa \(OpenAI\) — as single judge/)).toBeInTheDocument();
  });

  it('discloses cross-model judging: an enterprise contestant judges the others too', async () => {
    const { user } = setup({ 'GET /models': MIXED });
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: '@oa/gpt-4o' }));
    await user.click(screen.getByRole('radio', { name: 'Cross-model judging' }));
    expect(
      await screen.findByText(/oa \(OpenAI\) — as contestant and cross-model judge/),
    ).toBeInTheDocument();
  });

  it('splits the request estimate into local and per-provider counts', async () => {
    const { user } = setup({ 'GET /models': MIXED });
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: '@oa/gpt-4o' }));
    await pickSuite(user); // starter suite fixture: 3 cases total
    const est = await screen.findByTestId('request-breakdown');
    // each selected model gets 3 cases × 1 repeat = 3 generation requests, sent to its own destination
    expect(est).toHaveTextContent('Ollama (local): 3');
    expect(est).toHaveTextContent('oa (OpenAI): 3');
  });

  it('adds judgement requests to the destination breakdown for a single hosted judge', async () => {
    const { user } = setup({ 'GET /models': MIXED });
    await user.click(await model('qwen3:8b'));
    await user.click(screen.getByRole('checkbox', { name: 'llama3:8b' }));
    await pickSuite(user); // starter suite fixture: 3 cases, 1 of them generation
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    await user.selectOptions(screen.getByLabelText('Judge model'), '@oa/gpt-4o');
    const est = await screen.findByTestId('request-breakdown');
    // generation: 2 local models × 3 cases = 6, all local; judging: 1 generation case × 2 contestants = 2, sent to oa
    expect(est).toHaveTextContent('Ollama (local): 6');
    expect(est).toHaveTextContent('oa (OpenAI): 2');
  });

  it('blocks starting if the chosen judge loses its key after a refresh', async () => {
    const noKey = MIXED.map((m) =>
      m.name === '@oa/gpt-4o'
        ? {
            ...m,
            available: false,
            unavailable_reason: 'API key not set: environment variable OA_KEY is empty',
          }
        : m,
    );
    const { user } = setup({ 'GET /models': MIXED, 'GET /models?refresh=1': noKey });
    await user.click(await model('qwen3:8b'));
    await pickSuite(user);
    await user.click(screen.getByRole('radio', { name: 'Single judge model' }));
    await user.selectOptions(screen.getByLabelText('Judge model'), '@oa/gpt-4o');
    await waitFor(() => expect(startButton()).toBeEnabled());

    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(startButton()).toBeDisabled());
    expect(
      screen.getByText(
        'Judge @oa/gpt-4o is unavailable: API key not set: environment variable OA_KEY is empty',
      ),
    ).toBeInTheDocument();
  });
});
