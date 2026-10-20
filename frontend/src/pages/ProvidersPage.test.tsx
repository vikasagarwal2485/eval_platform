import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { jsonError, mockApi, renderApp } from '../test/utils';
import ProvidersPage from './ProvidersPage';

afterEach(() => vi.unstubAllGlobals());

const model = (over = {}) => ({
  id: 10,
  model_id: 'gpt-4o',
  ref: '@oa/gpt-4o',
  display_name: 'gpt-4o',
  enabled: true,
  reasoning: false,
  classification: false,
  ...over,
});
const provider = (over = {}) => ({
  id: 1,
  kind: 'openai',
  name: 'oa',
  key_env: 'OA_KEY',
  base_url: null,
  health_check_path: null,
  key_available: true,
  unavailable_reason: null,
  last_test_status: null,
  last_test_message: null,
  last_test_at: null,
  data_sharing_acknowledged_at: '2026-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
  models: [model()],
  ...over,
});

function setup(providers: unknown[] = [provider()], routes: Record<string, unknown> = {}) {
  const api = mockApi({ 'GET /providers': providers, ...routes });
  renderApp(<ProvidersPage />, { route: '/providers', path: '/providers' });
  return { ...api, user: userEvent.setup() };
}
const posted = (
  calls: { method: string; path: string; body: unknown }[],
  path: string,
  method = 'POST',
) => calls.filter((c) => c.method === method && c.path === path).map((c) => c.body);
const card = async () => screen.findByRole('region', { name: 'Provider oa' });

describe('empty, loading and error states', () => {
  it('explains what a provider is and how to set the key when none exist', async () => {
    setup([]);
    expect(await screen.findByText('No models registered yet')).toBeInTheDocument();
    expect(screen.getByText(/name of the environment variable/)).toBeInTheDocument();
    expect(screen.getByText(/export OPENAI_API_KEY/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Add a model' })).toBeInTheDocument();
  });

  it('shows loading and load errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    );
    renderApp(<ProvidersPage />, { route: '/providers', path: '/providers' });
    expect(screen.getByRole('status')).toHaveTextContent('Loading providers');
    vi.unstubAllGlobals();
    setup([], { 'GET /providers': () => jsonError(500, 'db exploded') });
    expect(await screen.findByText(/db exploded/)).toBeInTheDocument();
  });
});

describe('provider list', () => {
  it('shows kind, key status, variable and the acknowledgment', async () => {
    setup([
      provider(),
      provider({
        id: 2,
        kind: 'anthropic',
        name: 'an',
        key_env: 'AN_KEY',
        key_available: false,
        unavailable_reason: 'API key not set: environment variable AN_KEY is empty',
        models: [],
      }),
    ]);
    const oa = await card();
    expect(within(oa).getByText('OpenAI')).toBeInTheDocument();
    expect(within(oa).getByText('key ready')).toBeInTheDocument();
    expect(within(oa).getByText('OA_KEY')).toBeInTheDocument();
    expect(within(oa).getByText(/data sharing acknowledged/)).toBeInTheDocument();
    const an = screen.getByRole('region', { name: 'Provider an' });
    expect(within(an).getByText('unavailable')).toBeInTheDocument();
    expect(
      within(an).getByText(/API key not set: environment variable AN_KEY is empty/),
    ).toBeInTheDocument();
    expect(within(an).getByText('No models registered yet.')).toBeInTheDocument();
  });

  it('lists a provider’s models with their references', async () => {
    setup();
    const table = within(await card()).getByRole('table', { name: 'Models of oa' });
    expect(within(table).getByText('@oa/gpt-4o')).toBeInTheDocument();
    expect(within(table).getByRole('checkbox', { name: 'Enabled: @oa/gpt-4o' })).toBeChecked();
    expect(
      within(table).getByRole('checkbox', { name: 'Reasoning model: @oa/gpt-4o' }),
    ).not.toBeChecked();
  });
});

describe('registering a provider', () => {
  it('has no field that accepts an API key value', async () => {
    setup([]);
    await screen.findByRole('heading', { name: 'Add a model' });
    const form = screen.getByRole('form', { name: /add a model/i });
    const labels = within(form)
      .getAllByRole('textbox')
      .map((i) => (i as HTMLInputElement).labels?.[0]?.textContent);
    expect(labels).toEqual([
      expect.stringMatching(/^Name/),
      'API key environment variable',
      expect.stringMatching(/^Base URL/),
    ]);
    expect(form.querySelector('input[type=password]')).toBeNull();
    expect(within(form).queryByLabelText(/^api key$/i)).toBeNull();
    expect(within(form).getByText(/never stores, shows or exports it/)).toBeInTheDocument();
  });

  it('registers a provider with the acknowledgment', async () => {
    const { user, calls } = setup([], { 'POST /providers': provider() });
    await user.click(
      await screen.findByRole('checkbox', { name: /I understand that prompts and model outputs/ }),
    );
    await user.click(screen.getByRole('button', { name: 'Register' }));
    await waitFor(() => expect(posted(calls, '/providers')).toHaveLength(1));
    expect(posted(calls, '/providers')[0]).toEqual({
      kind: 'openai',
      name: 'openai',
      key_env: 'OPENAI_API_KEY',
      base_url: null,
      api_version: null,
      health_check_path: null,
      acknowledge_data_sharing: true,
    });
  });

  it('follows the kind with suggested name and variable until the user edits them', async () => {
    const { user } = setup([]);
    await screen.findByRole('heading', { name: 'Add a model' });
    await user.selectOptions(screen.getByLabelText('Provider'), 'anthropic');
    expect(screen.getByLabelText(/^Name/)).toHaveValue('anthropic');
    expect(screen.getByLabelText('API key environment variable')).toHaveValue('ANTHROPIC_API_KEY');
    await user.clear(screen.getByLabelText('API key environment variable'));
    await user.type(screen.getByLabelText('API key environment variable'), 'MY_CLAUDE_KEY');
    await user.selectOptions(screen.getByLabelText('Provider'), 'openai');
    expect(screen.getByLabelText(/^Name/)).toHaveValue('openai');
    expect(screen.getByLabelText('API key environment variable')).toHaveValue('MY_CLAUDE_KEY'); // edited: left alone
  });

  it('requires a base URL and API version for Azure OpenAI, shown only for that kind', async () => {
    const { user, calls } = setup([]);
    await screen.findByRole('heading', { name: 'Add a model' });
    expect(screen.queryByLabelText('API version')).toBeNull(); // not shown for openai
    await user.selectOptions(screen.getByLabelText('Provider'), 'azure-openai');
    expect(screen.getByLabelText(/^Name/)).toHaveValue('azure-openai');
    expect(screen.getByLabelText('API key environment variable')).toHaveValue(
      'AZURE_OPENAI_API_KEY',
    );
    expect(screen.getByLabelText('API version')).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: /I understand/ }));
    await user.click(screen.getByRole('button', { name: 'Register' }));
    expect(await screen.findByText(/Enter your Azure resource endpoint/)).toBeInTheDocument();
    expect(screen.getByText(/Enter the API version/)).toBeInTheDocument();
    expect(posted(calls, '/providers')).toHaveLength(0);
  });

  it('registers an Azure OpenAI provider with its base URL and API version', async () => {
    const { user, calls } = setup([], { 'POST /providers': provider({ kind: 'azure-openai' }) });
    await user.selectOptions(await screen.findByLabelText('Provider'), 'azure-openai');
    await user.type(screen.getByLabelText(/^Base URL/), 'https://my-resource.openai.azure.com');
    await user.type(screen.getByLabelText('API version'), '2024-12-01-preview');
    await user.click(screen.getByRole('checkbox', { name: /I understand/ }));
    await user.click(screen.getByRole('button', { name: 'Register' }));
    await waitFor(() => expect(posted(calls, '/providers')).toHaveLength(1));
    expect(posted(calls, '/providers')[0]).toEqual({
      kind: 'azure-openai',
      name: 'azure-openai',
      key_env: 'AZURE_OPENAI_API_KEY',
      base_url: 'https://my-resource.openai.azure.com',
      api_version: '2024-12-01-preview',
      health_check_path: null,
      acknowledge_data_sharing: true,
    });
  });

  it('refuses a key pasted into the variable field and explains', async () => {
    const { user, calls } = setup([]);
    await screen.findByRole('heading', { name: 'Add a model' });
    const env = screen.getByLabelText('API key environment variable');
    await user.clear(env);
    await user.type(env, 'sk-proj-abc123def456');
    await user.click(screen.getByRole('checkbox', { name: /I understand/ }));
    await user.click(screen.getByRole('button', { name: 'Register' }));
    expect(await screen.findByText(/That looks like an API key/)).toBeInTheDocument();
    expect(env).toHaveAttribute('aria-invalid', 'true');
    expect(posted(calls, '/providers')).toHaveLength(0);
  });

  it.each([
    ['name', /^Name/, 'Bad Name', /lowercase letters/],
    ['variable', 'API key environment variable', 'lower_case', /upper-case variable name/],
    ['base URL', /^Base URL/, 'ftp://x', /http:\/\/ or https:\/\//],
  ])('validates the %s before sending anything', async (_what, label, value, message) => {
    const { user, calls } = setup([]);
    await screen.findByRole('heading', { name: 'Add a model' });
    const input = screen.getByLabelText(label);
    await user.clear(input);
    await user.type(input, value);
    await user.click(screen.getByRole('checkbox', { name: /I understand/ }));
    await user.click(screen.getByRole('button', { name: 'Register' }));
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(posted(calls, '/providers')).toHaveLength(0);
  });

  it('requires the data-sharing acknowledgment', async () => {
    const { user, calls } = setup([]);
    await user.click(await screen.findByRole('button', { name: 'Register' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Acknowledge that evaluation content is sent to OpenAI/,
    );
    expect(posted(calls, '/providers')).toHaveLength(0);
  });

  it('shows a server-side error such as a duplicate name', async () => {
    const { user } = setup([], {
      'POST /providers': () => jsonError(409, "A provider named 'openai' already exists"),
    });
    await user.click(await screen.findByRole('checkbox', { name: /I understand/ }));
    await user.click(screen.getByRole('button', { name: 'Register' }));
    expect(await screen.findByText(/already exists/)).toBeInTheDocument();
  });
});

describe('testing the connection', () => {
  const test = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(within(await card()).getByRole('button', { name: 'Test connection' }));
    return within(await card()).findByRole('status');
  };

  it.each([
    ['working', 'The provider accepted the key.', 'working'],
    [
      'key_not_set',
      'API key not set: environment variable OA_KEY is empty. Export it and restart the application.',
      'key not set',
    ],
    [
      'authentication_failed',
      'Incorrect API key provided. Check the value of OA_KEY.',
      'authentication failed',
    ],
    ['rate_limited', 'slow down', 'rate limited'],
    ['unreachable', 'cannot reach oa (gave up after 3 attempts)', 'unreachable'],
  ])('reports %s', async (status, message, label) => {
    const { user, calls } = setup([provider()], {
      'POST /providers/1/test': { status, message, base_url: 'https://api.openai.com' },
    });
    const out = await test(user);
    expect(within(out).getByText(label)).toBeInTheDocument();
    expect(out).toHaveTextContent(message);
    expect(posted(calls, '/providers/1/test')).toHaveLength(1);
  });

  it('shows an error when the test request itself fails', async () => {
    const { user } = setup([provider()], {
      'POST /providers/1/test': () => jsonError(500, 'boom'),
    });
    await user.click(within(await card()).getByRole('button', { name: 'Test connection' }));
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });
});

describe('managing models', () => {
  it('adds a model by typing its id, optionally as a reasoning model', async () => {
    const { user, calls } = setup([provider()], { 'POST /providers/1/models': model({ id: 11 }) });
    const c = await card();
    expect(within(c).getByRole('button', { name: 'Add model' })).toBeDisabled();
    await user.type(within(c).getByLabelText('Model id'), '  o3 ');
    await user.click(within(c).getByRole('checkbox', { name: 'Reasoning model' }));
    await user.click(within(c).getByRole('button', { name: 'Add model' }));
    await waitFor(() => expect(posted(calls, '/providers/1/models')).toHaveLength(1));
    expect(posted(calls, '/providers/1/models')[0]).toEqual({
      model_id: 'o3',
      reasoning: true,
      reasoning_effort: null,
      classification: false,
    });
    expect(within(c).getByLabelText('Model id')).toHaveValue('');
  });

  it('sets an optional reasoning effort for a reasoning model', async () => {
    const { user, calls } = setup([provider()], { 'POST /providers/1/models': model({ id: 11 }) });
    const c = await card();
    await user.type(within(c).getByLabelText('Model id'), 'o3-mini');
    await user.click(within(c).getByRole('checkbox', { name: 'Reasoning model' }));
    await user.type(within(c).getByLabelText(/Reasoning effort/), 'low');
    await user.click(within(c).getByRole('button', { name: 'Add model' }));
    await waitFor(() => expect(posted(calls, '/providers/1/models')).toHaveLength(1));
    expect(posted(calls, '/providers/1/models')[0]).toEqual({
      model_id: 'o3-mini',
      reasoning: true,
      reasoning_effort: 'low',
      classification: false,
    });
  });

  it('adds a model flagged for classification', async () => {
    const { user, calls } = setup([provider()], { 'POST /providers/1/models': model({ id: 11 }) });
    const c = await card();
    await user.type(within(c).getByLabelText('Model id'), 'small-fast');
    await user.click(within(c).getByRole('checkbox', { name: 'Classification model' }));
    await user.click(within(c).getByRole('button', { name: 'Add model' }));
    await waitFor(() => expect(posted(calls, '/providers/1/models')).toHaveLength(1));
    expect(posted(calls, '/providers/1/models')[0]).toEqual({
      model_id: 'small-fast',
      reasoning: false,
      reasoning_effort: null,
      classification: true,
    });
  });

  it('shows why adding failed, for example a duplicate', async () => {
    const { user } = setup([provider()], {
      'POST /providers/1/models': () =>
        jsonError(409, "'gpt-4o' is already registered under provider 'oa'"),
    });
    const c = await card();
    await user.type(within(c).getByLabelText('Model id'), 'gpt-4o');
    await user.click(within(c).getByRole('button', { name: 'Add model' }));
    expect(await screen.findByText(/already registered/)).toBeInTheDocument();
  });

  it('enables, disables and flags reasoning models', async () => {
    const { user, calls } = setup([provider()], { 'PATCH /providers/1/models/10': model() });
    const c = await card();
    await user.click(within(c).getByRole('checkbox', { name: 'Enabled: @oa/gpt-4o' }));
    await user.click(within(c).getByRole('checkbox', { name: 'Reasoning model: @oa/gpt-4o' }));
    await waitFor(() => expect(posted(calls, '/providers/1/models/10', 'PATCH')).toHaveLength(2));
    expect(posted(calls, '/providers/1/models/10', 'PATCH')).toEqual([
      { enabled: false },
      { reasoning: true },
    ]);
  });

  it('flags a registered model for classification', async () => {
    const { user, calls } = setup([provider()], { 'PATCH /providers/1/models/10': model() });
    const c = await card();
    await user.click(within(c).getByRole('checkbox', { name: 'Classification model: @oa/gpt-4o' }));
    await waitFor(() => expect(posted(calls, '/providers/1/models/10', 'PATCH')).toHaveLength(1));
    expect(posted(calls, '/providers/1/models/10', 'PATCH')).toEqual([{ classification: true }]);
  });

  it('removes a model only after confirmation', async () => {
    const confirm = vi.fn(() => false);
    vi.stubGlobal('confirm', confirm);
    const { user, calls } = setup([provider()], {
      'DELETE /providers/1/models/10': new Response(null, { status: 204 }),
    });
    const c = await card();
    await user.click(within(c).getByRole('button', { name: 'Remove @oa/gpt-4o' }));
    expect(posted(calls, '/providers/1/models/10', 'DELETE')).toHaveLength(0);
    confirm.mockReturnValue(true);
    await user.click(within(c).getByRole('button', { name: 'Remove @oa/gpt-4o' }));
    await waitFor(() => expect(posted(calls, '/providers/1/models/10', 'DELETE')).toHaveLength(1));
  });
});

describe('fetching a provider’s model list', () => {
  const listing = {
    models: [
      { id: 'gpt-4o', already_added: true },
      { id: 'gpt-4o-mini', already_added: false },
      { id: 'o3', already_added: false },
    ],
  };

  it('lists models, marks registered ones, and adds the selected in one action', async () => {
    const { user, calls } = setup([provider()], {
      'GET /providers/1/available-models': listing,
      'POST /providers/1/models': model({ id: 12 }),
    });
    const c = await card();
    await user.click(within(c).getByRole('button', { name: /Fetch models from OpenAI/ }));
    const group = await within(c).findByRole('group', { name: /Models offered by OpenAI/ });
    const registered = within(group).getByRole('checkbox', { name: /gpt-4o \(already added\)/ });
    expect(registered).toBeDisabled();
    expect(registered).toBeChecked();
    const add = within(group).getByRole('button', { name: /Add selected \(0\)/ });
    expect(add).toBeDisabled();
    await user.click(within(group).getByRole('checkbox', { name: 'gpt-4o-mini' }));
    await user.click(within(group).getByRole('checkbox', { name: 'o3' }));
    await user.click(within(group).getByRole('button', { name: /Add selected \(2\)/ }));
    await waitFor(() => expect(posted(calls, '/providers/1/models')).toHaveLength(2));
    expect(
      posted(calls, '/providers/1/models').map((b) => (b as { model_id: string }).model_id),
    ).toEqual(['gpt-4o-mini', 'o3']);
    await waitFor(() =>
      expect(within(c).queryByRole('group', { name: /Models offered by/ })).toBeNull(),
    );
  });

  it('shows an actionable error but still lets the user type an id', async () => {
    const { user } = setup([provider()], {
      'GET /providers/1/available-models': () =>
        jsonError(502, {
          code: 'authentication_failed',
          message: 'Incorrect API key provided. Check the value of OA_KEY.',
        }),
    });
    const c = await card();
    await user.click(within(c).getByRole('button', { name: /Fetch models from OpenAI/ }));
    expect(await within(c).findByText(/Check the value of OA_KEY/)).toBeInTheDocument();
    expect(within(c).getByText(/You can still add a model by typing its id/)).toBeInTheDocument();
    await user.type(within(c).getByLabelText('Model id'), 'typed');
    expect(within(c).getByRole('button', { name: 'Add model' })).toBeEnabled();
  });
});

describe('editing and removing a provider', () => {
  it('changes the key variable name and base URL', async () => {
    const { user, calls } = setup([provider()], {
      'PATCH /providers/1': provider({ key_env: 'NEW_KEY' }),
    });
    const c = await card();
    await user.click(within(c).getByRole('button', { name: 'Edit' }));
    const env = within(c).getByLabelText('API key environment variable');
    await user.clear(env);
    await user.type(env, 'NEW_KEY');
    await user.type(within(c).getByLabelText('Base URL'), 'https://gw.example/v1');
    await user.click(within(c).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(posted(calls, '/providers/1', 'PATCH')).toHaveLength(1));
    expect(posted(calls, '/providers/1', 'PATCH')[0]).toEqual({
      key_env: 'NEW_KEY',
      base_url: 'https://gw.example/v1',
    });
  });

  it('refuses a key-shaped value when editing', async () => {
    const { user, calls } = setup([provider()]);
    const c = await card();
    await user.click(within(c).getByRole('button', { name: 'Edit' }));
    const env = within(c).getByLabelText('API key environment variable');
    await user.clear(env);
    await user.type(env, 'sk-ant-api03-xyz');
    await user.click(within(c).getByRole('button', { name: 'Save' }));
    expect(await within(c).findByRole('alert')).toHaveTextContent(/looks like an API key/);
    expect(posted(calls, '/providers/1', 'PATCH')).toHaveLength(0);
  });

  it('removes a provider after confirmation and shows why it cannot while a run uses it', async () => {
    const confirm = vi.fn(() => true);
    vi.stubGlobal('confirm', confirm);
    const { user } = setup([provider()], {
      'DELETE /providers/1': () =>
        jsonError(
          409,
          "Provider 'oa' is used by a queued or running run; let it finish or cancel it first",
        ),
    });
    await user.click(within(await card()).getByRole('button', { name: 'Remove provider oa' }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Past runs keep their results'));
    expect(await screen.findByText(/queued or running run/)).toBeInTheDocument();
  });
});

describe('Azure OpenAI provider card (4.3)', () => {
  const azure = (over = {}) =>
    provider({
      kind: 'azure-openai',
      name: 'az',
      key_env: 'AZ_KEY',
      base_url: 'https://my-resource.openai.azure.com',
      api_version: '2024-12-01-preview',
      models: [],
      ...over,
    });
  const azureCard = async () => screen.findByRole('region', { name: 'Provider az' });

  it('labels the model field "Deployment name" and has no fetch-models action', async () => {
    setup([azure()]);
    const c = await azureCard();
    expect(within(c).getByLabelText('Deployment name')).toBeInTheDocument();
    expect(within(c).queryByLabelText('Model id')).toBeNull();
    expect(within(c).queryByRole('button', { name: /Fetch models/ })).toBeNull();
    expect(within(c).getByText(/can.t be auto-discovered/)).toBeInTheDocument();
  });

  it('shows the API version and requires it when editing', async () => {
    const { user, calls } = setup([azure()]);
    const c = await azureCard();
    expect(within(c).getByText('2024-12-01-preview')).toBeInTheDocument();
    await user.click(within(c).getByRole('button', { name: 'Edit' }));
    const version = within(c).getByLabelText('API version');
    await user.clear(version);
    await user.click(within(c).getByRole('button', { name: 'Save' }));
    expect(await within(c).findByRole('alert')).toHaveTextContent(/enter the api version/i);
    expect(posted(calls, '/providers/1', 'PATCH')).toHaveLength(0);
  });

  it('reports no_deployments before any deployment is registered', async () => {
    const { user } = setup([azure()], {
      'POST /providers/1/test': {
        status: 'no_deployments',
        message: 'Register a deployment first, then test the connection against it.',
        base_url: 'https://my-resource.openai.azure.com',
      },
    });
    const c = await azureCard();
    await user.click(within(c).getByRole('button', { name: 'Test connection' }));
    const out = await within(c).findByRole('status');
    expect(within(out).getByText('no deployment to test')).toBeInTheDocument();
  });

  it('adds a deployment by name', async () => {
    const { user, calls } = setup([azure()], {
      'POST /providers/1/models': model({ id: 12, model_id: 'o3-mini', ref: '@az/o3-mini' }),
    });
    const c = await azureCard();
    await user.type(within(c).getByLabelText('Deployment name'), 'o3-mini');
    await user.click(within(c).getByRole('button', { name: 'Add model' }));
    await waitFor(() => expect(posted(calls, '/providers/1/models')).toHaveLength(1));
    expect(posted(calls, '/providers/1/models')[0]).toMatchObject({ model_id: 'o3-mini' });
  });
});

describe('Ollama provider card (add-ollama-provider-kind)', () => {
  const ollama = (over = {}) =>
    provider({
      kind: 'ollama',
      name: 'ollama-main',
      key_env: null,
      base_url: null,
      data_sharing_acknowledged_at: null,
      models: [],
      ...over,
    });
  const ollamaCard = async () => screen.findByRole('region', { name: 'Provider ollama-main' });

  it('the kind dropdown offers Ollama', async () => {
    const { user } = setup([]);
    await screen.findByRole('heading', { name: 'Add a model' });
    await user.selectOptions(screen.getByLabelText('Provider'), 'ollama');
    expect(screen.getByLabelText(/^Name/)).toHaveValue('ollama-main');
  });

  it('registering Ollama shows no key field and no data-sharing acknowledgment', async () => {
    const { user } = setup([]);
    await user.selectOptions(await screen.findByLabelText('Provider'), 'ollama');
    expect(screen.queryByLabelText('API key environment variable')).toBeNull();
    expect(screen.queryByRole('checkbox', { name: /I understand/ })).toBeNull();
    expect(screen.getByLabelText(/Ollama server URL/)).toBeInTheDocument();
  });

  it('registers an Ollama provider with no key and no acknowledgment required', async () => {
    const { user, calls } = setup([], { 'POST /providers': ollama() });
    await user.selectOptions(await screen.findByLabelText('Provider'), 'ollama');
    await user.click(screen.getByRole('button', { name: 'Register' }));
    await waitFor(() => expect(posted(calls, '/providers')).toHaveLength(1));
    expect(posted(calls, '/providers')[0]).toEqual({
      kind: 'ollama',
      name: 'ollama-main',
      key_env: null,
      base_url: null,
      api_version: null,
      health_check_path: null,
      acknowledge_data_sharing: false,
    });
  });

  it('shows "no key needed" instead of a key-ready/not-set badge', async () => {
    setup([ollama()]);
    const c = await ollamaCard();
    expect(within(c).getByText('no key needed')).toBeInTheDocument();
    expect(within(c).queryByText('key ready')).toBeNull();
    expect(within(c).queryByText('key not set')).toBeNull();
  });

  it('fetches and registers Ollama models one by one, like any other provider', async () => {
    const { user, calls } = setup([ollama()], {
      'GET /providers/1/available-models': { models: [{ id: 'qwen3:8b', already_added: false }] },
      'POST /providers/1/models': model({
        id: 20,
        model_id: 'qwen3:8b',
        ref: '@ollama-main/qwen3:8b',
      }),
    });
    const c = await ollamaCard();
    await user.click(within(c).getByRole('button', { name: /Fetch models from Ollama/ }));
    const group = await within(c).findByRole('group', { name: /Models offered by Ollama/ });
    await user.click(within(group).getByRole('checkbox', { name: 'qwen3:8b' }));
    await user.click(within(group).getByRole('button', { name: /Add selected \(1\)/ }));
    await waitFor(() => expect(posted(calls, '/providers/1/models')).toHaveLength(1));
    expect(posted(calls, '/providers/1/models')[0]).toMatchObject({ model_id: 'qwen3:8b' });
  });

  it('test connection reports unreachable, not key-related', async () => {
    const { user } = setup([ollama()], {
      'POST /providers/1/test': {
        status: 'unreachable',
        message: 'Cannot reach Ollama at http://localhost:11434',
        base_url: 'http://localhost:11434',
      },
    });
    const c = await ollamaCard();
    await user.click(within(c).getByRole('button', { name: 'Test connection' }));
    const out = await within(c).findByRole('status');
    expect(within(out).getByText('unreachable')).toBeInTheDocument();
    expect(out).toHaveTextContent('Cannot reach Ollama');
  });

  it('editing hides the key field and relabels the URL field', async () => {
    const { user } = setup([ollama()]);
    const c = await ollamaCard();
    await user.click(within(c).getByRole('button', { name: 'Edit' }));
    expect(within(c).queryByLabelText('API key environment variable')).toBeNull();
    expect(within(c).getByLabelText('Ollama server URL')).toBeInTheDocument();
  });
});

describe('Custom provider card (add-custom-model-provider-kind)', () => {
  const custom = (over = {}) =>
    provider({
      kind: 'custom',
      name: 'context-classifier',
      key_env: null,
      base_url: 'http://127.0.0.1:8765',
      health_check_path: null,
      data_sharing_acknowledged_at: null,
      models: [],
      ...over,
    });
  const customCard = async () => screen.findByRole('region', { name: 'Provider context-classifier' });

  it('the kind dropdown offers Custom', async () => {
    const { user } = setup([]);
    await screen.findByRole('heading', { name: 'Add a model' });
    await user.selectOptions(screen.getByLabelText('Provider'), 'custom');
    expect(screen.getByLabelText(/Service base URL/)).toBeInTheDocument();
    expect(screen.queryByLabelText('API key environment variable')).toBeNull();
    expect(screen.queryByRole('checkbox', { name: /I understand/ })).toBeNull();
  });

  it('requires a base URL', async () => {
    const { user, calls } = setup([]);
    await user.selectOptions(await screen.findByLabelText('Provider'), 'custom');
    await user.click(screen.getByRole('button', { name: 'Register' }));
    expect(await screen.findByText(/enter this service.s base url/i)).toBeInTheDocument();
    expect(posted(calls, '/providers')).toHaveLength(0);
  });

  it('registers a custom provider with an optional health-check path, no key and no acknowledgment', async () => {
    const { user, calls } = setup([], { 'POST /providers': custom() });
    await user.selectOptions(await screen.findByLabelText('Provider'), 'custom');
    await user.type(screen.getByLabelText(/Service base URL/), 'http://127.0.0.1:8765');
    await user.type(screen.getByLabelText(/Health-check path/), '/healthz');
    await user.click(screen.getByRole('button', { name: 'Register' }));
    await waitFor(() => expect(posted(calls, '/providers')).toHaveLength(1));
    expect(posted(calls, '/providers')[0]).toEqual({
      kind: 'custom',
      name: 'custom-model',
      key_env: null,
      base_url: 'http://127.0.0.1:8765',
      api_version: null,
      health_check_path: '/healthz',
      acknowledge_data_sharing: false,
    });
  });

  it('shows "no key needed" instead of a key-ready/not-set badge', async () => {
    setup([custom()]);
    const c = await customCard();
    expect(within(c).getByText('no key needed')).toBeInTheDocument();
    expect(within(c).queryByText('key ready')).toBeNull();
    expect(within(c).queryByText('key not set')).toBeNull();
  });

  it('auto-discovery is not offered for a custom provider', async () => {
    setup([custom()]);
    const c = await customCard();
    expect(within(c).queryByRole('button', { name: /Fetch models from/ })).toBeNull();
  });

  it('editing hides the key field and relabels the URL field', async () => {
    const { user } = setup([custom()]);
    const c = await customCard();
    await user.click(within(c).getByRole('button', { name: 'Edit' }));
    expect(within(c).queryByLabelText('API key environment variable')).toBeNull();
    expect(within(c).getByLabelText('Service base URL')).toBeInTheDocument();
  });
});
