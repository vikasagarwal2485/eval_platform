import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import type { TempoTrace } from '../api/types';
import { jsonError, mockApi } from '../test/utils';
import SpanTree from './SpanTree';

function render(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return rtlRender(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const TRACE_ID = 'a'.repeat(32);

function trace(): TempoTrace {
  return {
    batches: [
      {
        resource: { attributes: [] },
        scopeSpans: [
          {
            scope: { name: 'eval_agent_sdk' },
            spans: [
              {
                traceId: 'xjfjx9KzqckZvNJERZSY1g==',
                spanId: 'root==',
                name: 'agent.turn',
                kind: 'SPAN_KIND_INTERNAL',
                startTimeUnixNano: '1000000000',
                endTimeUnixNano: '5000000000',
                attributes: [],
                status: { code: 'STATUS_CODE_OK' },
              },
              {
                traceId: 'xjfjx9KzqckZvNJERZSY1g==',
                spanId: 'child==',
                parentSpanId: 'root==',
                name: 'gen_ai.chat',
                kind: 'SPAN_KIND_CLIENT',
                startTimeUnixNano: '2000000000',
                endTimeUnixNano: '4000000000',
                attributes: [
                  { key: 'gen_ai.request.model', value: { stringValue: 'gpt-4o' } },
                  { key: 'gen_ai.usage.input_tokens', value: { intValue: '10' } },
                  { key: 'eval.cost', value: { doubleValue: 0.0025 } },
                ],
                status: { code: 'STATUS_CODE_OK' },
              },
            ],
          },
        ],
      },
    ],
  };
}

describe('SpanTree', () => {
  it('shows "no trace recorded" when there is no trace id, without ever calling the API', async () => {
    const { fn } = mockApi({});
    render(<SpanTree traceId={null} />);
    const user = userEvent.setup();
    await user.click(screen.getByText('Trace'));
    expect(screen.getByText(/no trace recorded/i)).toBeInTheDocument();
    expect(fn).not.toHaveBeenCalled();
  });

  it('fetches lazily and renders the span tree once opened', async () => {
    mockApi({ [`GET /traces/${TRACE_ID}`]: trace() });
    render(<SpanTree traceId={TRACE_ID} />);
    expect(screen.queryByText('agent.turn')).not.toBeInTheDocument(); // not fetched before opening
    const user = userEvent.setup();
    await user.click(screen.getByText('Trace'));
    expect(await screen.findByText('agent.turn')).toBeInTheDocument();
    expect(screen.getByText('gen_ai.chat')).toBeInTheDocument();
    expect(screen.getByText(/gen_ai.request.model=gpt-4o/)).toBeInTheDocument();
  });

  it('shows a clear message for a trace that cannot be found', async () => {
    mockApi({
      [`GET /traces/${TRACE_ID}`]: jsonError(404, { code: 'trace_not_found', message: 'no trace' }),
    });
    render(<SpanTree traceId={TRACE_ID} />);
    const user = userEvent.setup();
    await user.click(screen.getByText('Trace'));
    expect(await screen.findByText(/no longer available/i)).toBeInTheDocument();
  });

  it('shows a clear message when Tempo is unreachable, without an error boundary', async () => {
    mockApi({
      [`GET /traces/${TRACE_ID}`]: jsonError(503, { code: 'tempo_unreachable', message: 'down' }),
    });
    render(<SpanTree traceId={TRACE_ID} />);
    const user = userEvent.setup();
    await user.click(screen.getByText('Trace'));
    expect(await screen.findByText(/tempo is unreachable/i)).toBeInTheDocument();
  });
});
