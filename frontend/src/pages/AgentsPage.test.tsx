import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { jsonError, mockApi, renderApp } from '../test/utils';
import AgentsPage from './AgentsPage';

afterEach(() => vi.unstubAllGlobals());

const agent = (over = {}) => ({
  id: 1,
  name: 'demo-chatbot',
  kind: 'chatbot',
  declared_models: { default: 'qwen3:8b' },
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
    await user.type(screen.getByLabelText('Model for declared model 1'), 'qwen3:8b');
    await user.click(screen.getByRole('button', { name: 'Register' }));
    expect(await screen.findByText('RAW-TOKEN-VALUE')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument();
    // the token never lingers once acknowledged
    await user.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByText('RAW-TOKEN-VALUE')).not.toBeInTheDocument();
  });

  it('sends a temperature override as a declared-model object, not a plain string', async () => {
    const { user, calls } = setup([], {
      'POST /agents': { ...agent({ name: 'new-bot' }), token: 'RAW-TOKEN-VALUE' },
    });
    await user.click(await screen.findByRole('button', { name: 'Register agent' }));
    await user.type(screen.getByLabelText('Name'), 'new-bot');
    await user.type(screen.getByLabelText('Model for declared model 1'), 'qwen3:8b');
    await user.type(screen.getByLabelText('Temperature for declared model 1'), '0.2');
    await user.click(screen.getByRole('button', { name: 'Register' }));
    await screen.findByText('RAW-TOKEN-VALUE');
    const post = calls.find((c) => c.method === 'POST' && c.path === '/agents');
    expect(post?.body.declared_models).toEqual({
      default: { model: 'qwen3:8b', params: { temperature: 0.2 } },
    });
  });

  it('leaves a declared model as a plain string when no temperature is set', async () => {
    const { user, calls } = setup([], {
      'POST /agents': { ...agent({ name: 'new-bot' }), token: 'RAW-TOKEN-VALUE' },
    });
    await user.click(await screen.findByRole('button', { name: 'Register agent' }));
    await user.type(screen.getByLabelText('Name'), 'new-bot');
    await user.type(screen.getByLabelText('Model for declared model 1'), 'qwen3:8b');
    await user.click(screen.getByRole('button', { name: 'Register' }));
    await screen.findByText('RAW-TOKEN-VALUE');
    const post = calls.find((c) => c.method === 'POST' && c.path === '/agents');
    expect(post?.body.declared_models).toEqual({ default: 'qwen3:8b' });
  });

  it('offers a closed dropdown of task types instead of free text', async () => {
    const { user, calls } = setup([], {
      'POST /agents': { ...agent({ name: 'new-bot' }), token: 'RAW-TOKEN-VALUE' },
    });
    await user.click(await screen.findByRole('button', { name: 'Register agent' }));
    await user.type(screen.getByLabelText('Name'), 'new-bot');

    const taskSelect = screen.getByLabelText('Task type for declared model 1') as HTMLSelectElement;
    expect(Array.from(taskSelect.options).map((o) => o.textContent)).toEqual([
      'Select a task…',
      'Reasoning',
      'Generation',
      'Classification',
      'Default (single, undifferentiated task)',
    ]);
    await user.selectOptions(taskSelect, 'reasoning');
    await user.type(screen.getByLabelText('Model for declared model 1'), 'qwen3:8b');

    await user.click(screen.getByRole('button', { name: '+ Add another model' }));
    await user.selectOptions(screen.getByLabelText('Task type for declared model 2'), 'generation');
    await user.type(screen.getByLabelText('Model for declared model 2'), 'qwen3:14b');

    await user.click(screen.getByRole('button', { name: 'Register' }));
    await screen.findByText('RAW-TOKEN-VALUE');
    const post = calls.find((c) => c.method === 'POST' && c.path === '/agents');
    expect(post?.body.declared_models).toEqual({ reasoning: 'qwen3:8b', generation: 'qwen3:14b' });
  });

  it('sends a fallback as part of the declared-model object, omitted entirely when blank', async () => {
    const { user, calls } = setup([], {
      'POST /agents': { ...agent({ name: 'new-bot' }), token: 'RAW-TOKEN-VALUE' },
    });
    await user.click(await screen.findByRole('button', { name: 'Register agent' }));
    await user.type(screen.getByLabelText('Name'), 'new-bot');
    await user.type(screen.getByLabelText('Model for declared model 1'), 'qwen3:8b');
    await user.type(screen.getByLabelText('Fallback model for declared model 1'), 'qwen3:14b');
    await user.click(screen.getByRole('button', { name: 'Register' }));
    await screen.findByText('RAW-TOKEN-VALUE');
    const post = calls.find((c) => c.method === 'POST' && c.path === '/agents');
    expect(post?.body.declared_models).toEqual({
      default: { model: 'qwen3:8b', fallback: 'qwen3:14b' },
    });
  });

  it('gates a hosted declared-model fallback behind a data-sharing acknowledgment, then registers', async () => {
    let acked = false;
    const { user } = setup([], {
      'POST /agents': () => {
        if (!acked)
          return jsonError(422, {
            code: 'ack_required',
            message: 'needs ack',
            provider: 'azure-main',
          });
        return { ...agent({ name: 'new-bot' }), token: 'RAW-TOKEN-VALUE' };
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Register agent' }));
    await user.type(screen.getByLabelText('Name'), 'new-bot');
    await user.type(screen.getByLabelText('Model for declared model 1'), 'qwen3:8b');
    await user.type(
      screen.getByLabelText('Fallback model for declared model 1'),
      '@azure-main/gpt-4o-mini',
    );
    await user.click(screen.getByRole('button', { name: 'Register' }));
    const ackButton = await screen.findByRole('button', { name: 'Acknowledge and register' });
    acked = true;
    await user.click(ackButton);
    await user.click(screen.getByRole('button', { name: 'Register' }));
    expect(await screen.findByText('RAW-TOKEN-VALUE')).toBeInTheDocument();
  });

  it('gates a hosted declared model behind a data-sharing acknowledgment, then registers', async () => {
    let acked = false;
    const { user } = setup([], {
      'POST /agents': () => {
        if (!acked)
          return jsonError(422, {
            code: 'ack_required',
            message: 'needs ack',
            provider: 'azure-main',
          });
        return { ...agent({ name: 'new-bot' }), token: 'RAW-TOKEN-VALUE' };
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Register agent' }));
    await user.type(screen.getByLabelText('Name'), 'new-bot');
    await user.type(screen.getByLabelText('Model for declared model 1'), '@azure-main/gpt-4o-mini');
    await user.click(screen.getByRole('button', { name: 'Register' }));
    const ackButton = await screen.findByRole('button', { name: 'Acknowledge and register' });
    acked = true;
    await user.click(ackButton);
    await user.click(screen.getByRole('button', { name: 'Register' }));
    expect(await screen.findByText('RAW-TOKEN-VALUE')).toBeInTheDocument();
  });

  it('shows a non-ok gateway_sync result after registering', async () => {
    const { user } = setup([], {
      'POST /agents': {
        ...agent({ name: 'new-bot' }),
        token: 'RAW-TOKEN-VALUE',
        gateway_sync: { default: { status: 'error', detail: 'gateway unreachable' } },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Register agent' }));
    await user.type(screen.getByLabelText('Name'), 'new-bot');
    await user.type(screen.getByLabelText('Model for declared model 1'), 'qwen3:8b');
    await user.click(screen.getByRole('button', { name: 'Register' }));
    expect(await screen.findByText(/Gateway sync error/)).toBeInTheDocument();
    expect(screen.getByText(/gateway unreachable/)).toBeInTheDocument();
  });
});
