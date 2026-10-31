import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { FakeEventSource } from '../../test/fakeEventSource';
import { mockApi } from '../../test/utils';
import type { Agent } from '../../api/types';
import PlaygroundPanel from './PlaygroundPanel';

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
});
afterEach(() => {
  vi.unstubAllGlobals();
  FakeEventSource.instances = [];
});

function render(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return rtlRender(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const CATALOG = [
  { id: 'chatbot', kind: 'chatbot', description: 'A single-call chatbot', task_slots: ['default'], accepts: [] },
  {
    id: 'reasoning',
    kind: 'reasoning',
    description: 'A multi-step reasoning pipeline',
    task_slots: ['classification', 'reasoning', 'generation'],
    accepts: [],
  },
  { id: 'router', kind: 'router', description: 'A classifier-router orchestrator', task_slots: ['routing'], accepts: [] },
];

function agent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 1,
    name: 'demo-chatbot',
    kind: 'chatbot',
    declared_models: { default: 'author:1' },
    status: 'active',
    liveness: 'idle',
    token_prefix: 'abcd1234',
    eval_config: {
      evaluators: [],
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
    ...overrides,
  };
}

function setup(routes: Record<string, unknown> = {}, a: Agent = agent()) {
  const api = mockApi({
    'GET /agents/catalog': CATALOG,
    'GET /skills': [],
    'GET /agents/1/turns': [],
    ...routes,
  });
  render(<PlaygroundPanel agent={a} />);
  return { ...api, user: userEvent.setup() };
}

describe('PlaygroundPanel', () => {
  it('shows a loading state while the catalog loads', async () => {
    const api = mockApi({ 'GET /agents/catalog': () => new Promise(() => {}) });
    render(<PlaygroundPanel agent={agent()} />);
    expect(screen.getByText(/Loading agent catalog/i)).toBeInTheDocument();
    expect(api.fn).toHaveBeenCalled();
  });

  it('shows an error state when the catalog fails to load', async () => {
    mockApi({ 'GET /agents/catalog': () => new Response('', { status: 500 }) });
    render(<PlaygroundPanel agent={agent()} />);
    expect(await screen.findByText(/Could not load the agent catalog/i)).toBeInTheDocument();
  });

  it('offers to enable the Playground when the agent is not yet eligible', async () => {
    setup({}, agent({ playground_eligible: false }));
    expect(await screen.findByText('Enable the Playground for this agent')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Enable Playground' })).toBeDisabled();
  });

  it('shows an empty state when no catalog flavor matches the agent kind', async () => {
    setup(
      { 'GET /agents/catalog': [] },
      agent({ playground_eligible: false }),
    );
    expect(await screen.findByText('No matching catalog flavor')).toBeInTheDocument();
  });

  it('enables the Playground and shows the one-time token', async () => {
    const { user } = setup(
      { 'POST /agents/1/playground/enable': { ...agent({ playground_eligible: true, flavor: 'chatbot' }), token: 'RAW-TOK' } },
      agent({ playground_eligible: false }),
    );
    await screen.findByText('Enable the Playground for this agent');
    await user.selectOptions(screen.getByLabelText('Flavor'), 'chatbot');
    await user.click(screen.getByRole('button', { name: 'Enable Playground' }));
    expect(await screen.findByText('RAW-TOK')).toBeInTheDocument();
  });

  it('shows the spawn form and live-conversation panel for an eligible agent', async () => {
    setup({}, agent({ playground_eligible: true, flavor: 'chatbot', playground_gateway_key_configured: true }));
    expect(await screen.findByRole('heading', { name: 'Spawn' })).toBeInTheDocument();
    expect(screen.getByLabelText('Task')).toBeInTheDocument();
    expect(screen.getByText('Live conversation')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Spawn' })).toBeDisabled();
  });

  it('enables the Spawn button once a task is typed, and submits the expected payload', async () => {
    const { user, calls } = setup(
      { 'POST /agents/1/playground/spawn': { status: 'ok' } },
      agent({ playground_eligible: true, flavor: 'chatbot', playground_gateway_key_configured: true }),
    );
    await user.type(await screen.findByLabelText('Task'), '2+2?');
    await user.type(screen.getByLabelText('System prompt (optional)'), 'be terse');
    const spawnButton = screen.getByRole('button', { name: 'Spawn' });
    expect(spawnButton).toBeEnabled();
    await user.click(spawnButton);
    expect(await screen.findByText(/Spawn finished/i)).toBeInTheDocument();
    const spawnCall = calls.find((c) => c.path === '/agents/1/playground/spawn');
    expect(spawnCall?.body).toEqual({ system_prompt: 'be terse', skills: [], task: '2+2?' });
  });

  it('reports a spawn failure without crashing', async () => {
    const { user } = setup(
      { 'POST /agents/1/playground/spawn': { status: 'error', returncode: 1, stderr: 'boom' } },
      agent({ playground_eligible: true, flavor: 'chatbot', playground_gateway_key_configured: true }),
    );
    await user.type(await screen.findByLabelText('Task'), 'hi');
    await user.click(screen.getByRole('button', { name: 'Spawn' }));
    expect(await screen.findByText(/Spawn error: boom/i)).toBeInTheDocument();
  });

  it('warns when a router agent has no hand-off target configured', async () => {
    setup(
      {},
      agent({
        kind: 'router',
        playground_eligible: true,
        flavor: 'router',
        playground_gateway_key_configured: true,
        handoff_agent_names: [],
      }),
    );
    expect(await screen.findByText(/no hand-off agents configured/i)).toBeInTheDocument();
  });

  it('warns when no gateway virtual key is stored for a gateway-routed flavor', async () => {
    setup(
      {},
      agent({
        kind: 'reasoning',
        playground_eligible: true,
        flavor: 'reasoning',
        playground_gateway_key_configured: false,
      }),
    );
    expect(await screen.findByText(/No gateway virtual key is stored/i)).toBeInTheDocument();
  });

  it('disables the Playground when confirmed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { user, calls } = setup(
      { 'POST /agents/1/playground/disable': agent({ playground_eligible: false }) },
      agent({ playground_eligible: true, flavor: 'chatbot', playground_gateway_key_configured: true }),
    );
    await user.click(await screen.findByRole('button', { name: 'Disable Playground' }));
    expect(calls.some((c) => c.path === '/agents/1/playground/disable')).toBe(true);
  });
});
