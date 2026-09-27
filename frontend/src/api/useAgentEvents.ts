import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useReducer } from 'react';
import { keys } from './hooks';

export interface AgentLiveState {
  connection: 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed';
  feed: { id: number; type: string; data: Record<string, unknown> }[];
}

export const initialAgentLive: AgentLiveState = { connection: 'idle', feed: [] };

type Action =
  | { type: '__connecting' | '__open' | '__reconnecting' | '__closed' }
  | { type: string; id: number; data: Record<string, unknown> };

const FEED_LIMIT = 200;

export function agentLiveReducer(s: AgentLiveState, a: Action): AgentLiveState {
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
      return s;
    default: {
      if (!('id' in a)) return s;
      const feed = [...s.feed, { id: a.id, type: a.type, data: a.data }];
      return { ...s, feed: feed.length > FEED_LIMIT ? feed.slice(feed.length - FEED_LIMIT) : feed };
    }
  }
}

const EVENT_TYPES = [
  'state',
  'turn_started',
  'span_added',
  'turn_finished',
  'evaluation_started',
  'evaluation_progress',
  'evaluation_finished',
  'agent_status',
];

const RESYNC_ON = new Set(['turn_finished', 'evaluation_finished']);

/**
 * Subscribe to an agent's live feed. Unlike a benchmark run's stream, this one never terminates on its own - the
 * agent may send events indefinitely (design D9) - so this hook only closes on unmount or a permanent error.
 */
export function useAgentEvents(agentId: number | null, enabled = true): AgentLiveState {
  const qc = useQueryClient();
  const [state, dispatch] = useReducer(agentLiveReducer, initialAgentLive);

  useEffect(() => {
    if (agentId === null || !enabled || typeof EventSource === 'undefined') return;
    dispatch({ type: '__connecting' });
    const es = new EventSource(`/api/agents/${agentId}/events`);

    es.onopen = () => dispatch({ type: '__open' });
    es.onerror = () => {
      if (es.readyState === 2 /* CLOSED */) dispatch({ type: '__closed' });
      else dispatch({ type: '__reconnecting' });
    };
    for (const type of EVENT_TYPES) {
      es.addEventListener(type, (ev) => {
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse((ev as MessageEvent).data);
        } catch {
          /* ignore malformed frames */
        }
        dispatch({ type, id: Number((ev as MessageEvent).lastEventId) || 0, data });
        if (RESYNC_ON.has(type)) {
          qc.invalidateQueries({ queryKey: ['agent-turns', agentId] });
          qc.invalidateQueries({ queryKey: ['agent-summary', agentId] });
          if (typeof data.turn_id === 'number')
            qc.invalidateQueries({ queryKey: keys.agentTurn(agentId, data.turn_id) });
        }
      });
    }
    return () => es.close();
  }, [agentId, enabled, qc]);

  return state;
}
