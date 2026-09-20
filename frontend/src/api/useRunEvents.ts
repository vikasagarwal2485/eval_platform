import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useReducer } from 'react';
import { keys } from './hooks';
import type { ResultEvent } from './types';

export interface LiveState {
  connection: 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed';
  finished: boolean;
  finalStatus: string | null;
  error: string | null;
  progress: { completed: number; total: number } | null;
  current: { model?: string; case_id?: number; case_title?: string; repeat?: number };
  results: ResultEvent[];
  preview: { model: string; case_id: number; answer: string; thinking: string } | null;
  scoring: { done: number; total: number } | null;
  warnings: string[];
}

export const initialLive: LiveState = {
  connection: 'idle',
  finished: false,
  finalStatus: null,
  error: null,
  progress: null,
  current: {},
  results: [],
  preview: null,
  scoring: null,
  warnings: [],
};

type Action = { type: string; data?: Record<string, any> } | { type: '__reset' }; // eslint-disable-line @typescript-eslint/no-explicit-any

const TERMINAL_STATUSES = ['completed', 'cancelled', 'failed'];

export function liveReducer(s: LiveState, a: Action): LiveState {
  if (a.type === '__reset') return initialLive;
  const d = ('data' in a && a.data) || {};
  switch (a.type) {
    case '__connecting':
      return { ...s, connection: 'connecting' };
    case '__open':
      return { ...s, connection: 'open' };
    case '__reconnecting':
      return { ...s, connection: 'reconnecting' };
    case '__closed':
      return { ...s, connection: 'closed' };
    case 'state':
      return { ...s, progress: d.progress ?? s.progress, current: d.current ?? s.current };
    case 'run_started':
      return { ...s, progress: { completed: 0, total: d.total } };
    case 'model_started':
      return { ...s, current: { ...s.current, model: d.model } };
    case 'request_started':
      return {
        ...s,
        current: { model: d.model, case_id: d.case_id, case_title: d.case_title, repeat: d.repeat },
        preview: { model: d.model, case_id: d.case_id, answer: '', thinking: '' },
      };
    case 'token': {
      // Append to the running preview only if it is for the same request; otherwise start fresh.
      const prev =
        s.preview && s.preview.case_id === d.case_id && s.preview.model === d.model
          ? s.preview
          : null;
      return {
        ...s,
        preview: {
          model: d.model,
          case_id: d.case_id,
          answer: (prev?.answer ?? '') + (d.answer ?? ''),
          thinking: (prev?.thinking ?? '') + (d.thinking ?? ''),
        },
      };
    }
    case 'result_completed':
      return { ...s, results: [...s.results, d as ResultEvent] };
    case 'progress':
      return { ...s, progress: { completed: d.completed, total: d.total } };
    case 'scoring_started':
      return { ...s, preview: null, scoring: { done: 0, total: 0 } };
    case 'scoring_progress':
      return { ...s, scoring: { done: d.done, total: d.total } };
    case 'warning':
      return { ...s, warnings: [...s.warnings, `${d.model}: ${d.message}`] };
    case 'run_finished':
      return { ...s, finished: true, finalStatus: d.status, error: d.error ?? null, preview: null };
    case 'rescore_finished':
      return {
        ...s,
        finished: true,
        finalStatus: d.error ? 'failed' : 'completed',
        error: d.error ?? null,
      };
    default:
      return s;
  }
}

const EVENT_TYPES = [
  'state',
  'queued',
  'run_started',
  'model_started',
  'request_started',
  'token',
  'result_completed',
  'progress',
  'scoring_started',
  'scoring_progress',
  'warning',
  'run_finished',
  'rescore_started',
  'rescore_finished',
];

/**
 * Subscribe to a run's Server-Sent Events. Events are hints; on (re)connect and on completion the
 * relevant queries are invalidated so the UI resyncs from the database.
 */
export function useRunEvents(runId: number | null, enabled = true): LiveState {
  const qc = useQueryClient();
  const [state, dispatch] = useReducer(liveReducer, initialLive);

  useEffect(() => {
    if (runId === null || !enabled || typeof EventSource === 'undefined') return;
    dispatch({ type: '__reset' });
    dispatch({ type: '__connecting' });
    const es = new EventSource(`/api/runs/${runId}/events`);
    let opened = false;

    const resync = () => {
      qc.invalidateQueries({ queryKey: keys.run(runId) });
      qc.invalidateQueries({ queryKey: keys.runs });
    };
    const finish = () => {
      es.close();
      dispatch({ type: '__closed' });
      resync();
      qc.invalidateQueries({ queryKey: ['summary', runId] });
      qc.invalidateQueries({ queryKey: ['results', runId] });
    };

    es.onopen = () => {
      dispatch({ type: '__open' });
      if (opened) resync(); // came back after a drop: catch up from the DB
      opened = true;
    };
    es.onerror = () => {
      if (es.readyState === 2 /* CLOSED */) dispatch({ type: '__closed' });
      else dispatch({ type: '__reconnecting' }); // the browser retries on its own
    };
    for (const type of EVENT_TYPES) {
      es.addEventListener(type, (ev) => {
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse((ev as MessageEvent).data);
        } catch {
          /* ignore malformed frames */
        }
        dispatch({ type, data });
        if (type === 'result_completed') qc.invalidateQueries({ queryKey: ['results', runId] });
        if (type === 'run_finished' || type === 'rescore_finished') finish();
        if (type === 'state' && TERMINAL_STATUSES.includes(String(data.status)) && !data.busy)
          finish();
      });
    }
    return () => es.close();
  }, [runId, enabled, qc]);

  return state;
}
