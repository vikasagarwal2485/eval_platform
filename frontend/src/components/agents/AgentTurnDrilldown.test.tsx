import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import type { AgentSpan, AgentTurnDetail } from '../../api/types';
import { mockApi } from '../../test/utils';
import AgentTurnDrilldown from './AgentTurnDrilldown';

function render(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return rtlRender(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function turn(overrides: Partial<AgentTurnDetail> = {}): AgentTurnDetail {
  return {
    id: 1,
    external_id: 't1',
    session_id: 's1',
    seq: 0,
    status: 'ok',
    input: 'hi',
    output: 'hello there',
    reference: null,
    system_prompt: null,
    error: null,
    models: ['qwen3:8b'],
    models_unknown: false,
    truncated: false,
    latency_ms: 120,
    prompt_tokens: 10,
    completion_tokens: 5,
    cost: null,
    trace_id: null,
    started_at: '2026-01-01T00:00:00Z',
    ended_at: '2026-01-01T00:00:01Z',
    latest_evaluation: null,
    spans: [],
    evaluations: [],
    ...overrides,
  };
}

const legacySpan: AgentSpan = {
  id: 1,
  kind: 'llm',
  model: 'qwen3:8b',
  name: null,
  input: {},
  output: 'legacy span output',
  thinking: null,
  error: null,
  started_at: null,
  ended_at: null,
  latency_ms: 80,
  ttft_ms: null,
  prompt_tokens: 10,
  completion_tokens: 5,
};

describe('add-agent-playground: system prompt', () => {
  it('shows the system prompt in its own collapsible section when the turn has one', () => {
    render(<AgentTurnDrilldown agentId={1} turn={turn({ system_prompt: 'be terse' })} />);
    expect(screen.getByText('System prompt')).toBeInTheDocument(); // the <summary> toggle
    expect(screen.getByText('be terse')).toBeInTheDocument();
  });

  it('omits the section entirely when the turn had no system prompt', () => {
    render(<AgentTurnDrilldown agentId={1} turn={turn({ system_prompt: null })} />);
    expect(screen.queryByText('System prompt')).not.toBeInTheDocument();
  });
});

describe('add-otel-tracing 8.3: agent turn drill-down', () => {
  it('shows the live span tree when the turn has a trace_id', async () => {
    const traceId = 'c'.repeat(32);
    mockApi({
      [`GET /traces/${traceId}`]: {
        batches: [
          { scopeSpans: [{ spans: [{ traceId: 'x', spanId: 's1', name: 'gen_ai.chat', startTimeUnixNano: '0', endTimeUnixNano: '1', attributes: [] }] }] },
        ],
      },
    });
    render(<AgentTurnDrilldown agentId={1} turn={turn({ trace_id: traceId })} />);
    const user = userEvent.setup();
    await user.click(screen.getByText('Trace'));
    expect(await screen.findByText('gen_ai.chat')).toBeInTheDocument();
    expect(screen.queryByText(/recorded before live tracing/i)).not.toBeInTheDocument();
  });

  it('falls back to showing legacy spans when there is no trace_id but spans were recorded', () => {
    render(<AgentTurnDrilldown agentId={1} turn={turn({ trace_id: null, spans: [legacySpan] })} />);
    expect(screen.getByText(/recorded before live tracing/i)).toBeInTheDocument();
    expect(screen.getByText('legacy span output')).toBeInTheDocument();
  });

  it('shows "no trace recorded" without hiding the rest of the turn when there is neither', async () => {
    render(<AgentTurnDrilldown agentId={1} turn={turn({ trace_id: null, spans: [] })} />);
    const user = userEvent.setup();
    await user.click(screen.getByText('Trace'));
    expect(screen.getByText(/no trace recorded/i)).toBeInTheDocument();
    expect(screen.getByText('hello there')).toBeInTheDocument(); // the turn's own output, unaffected
  });
});
