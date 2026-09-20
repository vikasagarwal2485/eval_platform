import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { ApiError, api, describeError } from './client';
import { FakeEventSource } from '../test/fakeEventSource';
import { initialLive, liveReducer, useRunEvents } from './useRunEvents';

function setup(runId = 7) {
  const qc = new QueryClient();
  const spy = vi.spyOn(qc, 'invalidateQueries');
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useRunEvents(runId), { wrapper });
  return { ...hook, spy, es: FakeEventSource.instances.at(-1)! };
}

describe('useRunEvents', () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal('EventSource', FakeEventSource);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('connects to the run event stream', () => {
    const { es, result } = setup(7);
    expect(es.url).toBe('/api/runs/7/events');
    expect(result.current.connection).toBe('connecting');
    act(() => es.open());
    expect(result.current.connection).toBe('open');
  });

  it('updates progress, current item, results and preview from events', () => {
    const { es, result } = setup();
    act(() => {
      es.open();
      es.emit('state', {
        status: 'running',
        progress: { completed: 0, total: 4 },
        current: {},
        busy: true,
      });
      es.emit('run_started', { total: 4 });
      es.emit('request_started', {
        model: 'a:1',
        case_id: 3,
        case_title: 'Bat and ball',
        repeat: 0,
      });
      es.emit('token', { model: 'a:1', case_id: 3, answer: 'Hel', thinking: 'hmm ' });
      es.emit('token', { model: 'a:1', case_id: 3, answer: 'lo', thinking: '' });
    });
    expect(result.current.progress).toEqual({ completed: 0, total: 4 });
    expect(result.current.current).toMatchObject({ model: 'a:1', case_title: 'Bat and ball' });
    expect(result.current.preview).toMatchObject({ answer: 'Hello', thinking: 'hmm ' });

    act(() => {
      es.emit('result_completed', {
        result_id: 1,
        model: 'a:1',
        case_id: 3,
        outcome: 'correct',
        value: 1,
      });
      es.emit('progress', { completed: 1, total: 4 });
    });
    expect(result.current.results).toHaveLength(1);
    expect(result.current.progress).toEqual({ completed: 1, total: 4 });
  });

  it('starts a new preview for each request', () => {
    const { es, result } = setup();
    act(() => {
      es.emit('request_started', { model: 'a:1', case_id: 1, repeat: 0 });
      es.emit('token', { model: 'a:1', case_id: 1, answer: 'first', thinking: '' });
      es.emit('request_started', { model: 'a:1', case_id: 2, repeat: 0 });
      es.emit('token', { model: 'a:1', case_id: 2, answer: 'second', thinking: '' });
    });
    expect(result.current.preview?.answer).toBe('second');
  });

  it('resyncs from the server when the connection drops and comes back', () => {
    const { es, result, spy } = setup(9);
    act(() => es.open());
    spy.mockClear();
    act(() => es.drop());
    expect(result.current.connection).toBe('reconnecting');
    expect(spy).not.toHaveBeenCalled();
    act(() => es.open());
    expect(result.current.connection).toBe('open');
    const invalidated = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(invalidated).toContain(JSON.stringify(['run', 9]));
  });

  it('closes the stream and refetches on run_finished', () => {
    const { es, result, spy } = setup(5);
    act(() => {
      es.open();
      es.emit('run_finished', { status: 'completed', error: null });
    });
    expect(es.closed).toBe(true);
    expect(result.current).toMatchObject({
      finished: true,
      finalStatus: 'completed',
      connection: 'closed',
    });
    const invalidated = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(invalidated).toEqual(
      expect.arrayContaining([JSON.stringify(['run', 5]), JSON.stringify(['summary', 5])]),
    );
  });

  it('closes immediately when the run is already finished', () => {
    const { es, result } = setup();
    act(() =>
      es.emit('state', {
        status: 'completed',
        busy: false,
        progress: { completed: 4, total: 4 },
        current: {},
      }),
    );
    expect(es.closed).toBe(true);
    expect(result.current.connection).toBe('closed');
  });

  it('closes the EventSource on unmount', () => {
    const { es, unmount } = setup();
    unmount();
    expect(es.closed).toBe(true);
  });

  it('records failures and warnings', () => {
    const { es, result } = setup();
    act(() => {
      es.emit('warning', { model: 'a:1', message: 'warm-up failed' });
      es.emit('run_finished', { status: 'failed', error: 'Ollama unreachable' });
    });
    expect(result.current.warnings).toEqual(['a:1: warm-up failed']);
    expect(result.current).toMatchObject({ finalStatus: 'failed', error: 'Ollama unreachable' });
  });
});

describe('liveReducer', () => {
  it('ignores unknown events', () => {
    expect(liveReducer(initialLive, { type: 'mystery', data: {} })).toBe(initialLive);
  });
});

describe('api client', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('formats FastAPI, custom and import errors readably', () => {
    expect(
      describeError(422, {
        detail: [{ loc: ['body', 'cases', 1, 'prompt'], msg: 'must not be empty' }],
      }),
    ).toBe('cases.1.prompt: must not be empty');
    expect(
      describeError(422, { detail: { code: 'no_models', message: 'Select at least one model.' } }),
    ).toBe('Select at least one model.');
    expect(
      describeError(422, {
        detail: { code: 'invalid_suite_file', errors: [{ field: 'cases[0]', message: 'bad' }] },
      }),
    ).toBe('cases[0]: bad');
    expect(describeError(409, { detail: 'A suite named x already exists' })).toBe(
      'A suite named x already exists',
    );
    expect(describeError(500, null)).toBe('Request failed (500)');
  });

  it('throws ApiError with status, message and code', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ detail: { code: 'ollama_unreachable', message: 'down' } }),
            { status: 503 },
          ),
        ),
    );
    const err = await api.get('/models').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 503, message: 'down', code: 'ollama_unreachable' });
  });

  it('reports an unreachable backend', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const err = await api.get('/health').catch((e) => e);
    expect(err).toMatchObject({ status: 0, code: 'backend_unreachable' });
  });

  it('handles 204 and sends JSON bodies', async () => {
    const f = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', f);
    await expect(api.delete('/runs/1')).resolves.toBeUndefined();
    await api.post('/runs', { a: 1 });
    expect(f).toHaveBeenLastCalledWith(
      '/api/runs',
      expect.objectContaining({ method: 'POST', body: '{"a":1}' }),
    );
  });
});
