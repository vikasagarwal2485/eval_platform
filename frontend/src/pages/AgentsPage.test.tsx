import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { mockApi, renderApp } from '../test/utils';
import AgentsPage from './AgentsPage';

afterEach(() => vi.unstubAllGlobals());

const agent = (over = {}) => ({
  id: 1,
  name: 'demo-chatbot',
  kind: 'chatbot',
  declared_model: 'qwen3:8b',
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
  ...over,
});

function setup(agents: unknown[] = [], routes: Record<string, unknown> = {}) {
  const api = mockApi({ 'GET /agents': agents, ...routes });
  renderApp(<AgentsPage />, { route: '/agents', path: '/agents' });
  return { ...api, user: userEvent.setup() };
}

describe('empty state', () => {
  it('explains how to connect an agent', async () => {
    setup([]);
    expect(await screen.findByText('No agents connected yet')).toBeInTheDocument();
    expect(screen.getByText(/python -m agents.chatbot/)).toBeInTheDocument();
  });
});

describe('agents list', () => {
  it('shows each agent with its kind, model and liveness', async () => {
    setup([agent(), agent({ id: 2, name: 'demo-reasoner', kind: 'reasoning', liveness: 'live' })]);
    expect(await screen.findByText('demo-chatbot')).toBeInTheDocument();
    expect(screen.getByText('demo-reasoner')).toBeInTheDocument();
    expect(screen.getAllByText('qwen3:8b').length).toBe(2);
    expect(screen.getAllByText('live').length).toBeGreaterThan(0);
  });

  it('links each card to its detail page', async () => {
    setup([agent()]);
    const link = await screen.findByRole('link', { name: /demo-chatbot/ });
    expect(link).toHaveAttribute('href', '/agents/1');
  });
});

describe('registration', () => {
  it('shows the ingest token exactly once after registering', async () => {
    const { user } = setup([], {
      'POST /agents': { ...agent({ name: 'new-bot' }), token: 'RAW-TOKEN-VALUE' },
    });
    await user.click(await screen.findByRole('button', { name: 'Register agent' }));
    await user.type(screen.getByLabelText('Name'), 'new-bot');
    await user.type(screen.getByLabelText('Declared model'), 'qwen3:8b');
    await user.click(screen.getByRole('button', { name: 'Register' }));
    expect(await screen.findByText('RAW-TOKEN-VALUE')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument();
    // the token never lingers once acknowledged
    await user.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByText('RAW-TOKEN-VALUE')).not.toBeInTheDocument();
  });
});
