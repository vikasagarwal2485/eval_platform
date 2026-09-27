import { useMemo, useState } from 'react';
import { useAgentTurn, useAgentTurns } from '../../api/hooks';
import { useAgentEvents } from '../../api/useAgentEvents';
import type { AgentTurn } from '../../api/types';
import { fmtDate, fmtPct } from '../../lib/format';
import AgentTurnDrilldown from './AgentTurnDrilldown';
import { Empty, ErrorBox, Spinner } from '../ui';

function TurnBadge({ turn }: { turn: AgentTurn }) {
  if (turn.status !== 'ok') return <span className="badge bad">{turn.status}</span>;
  const ev = turn.latest_evaluation;
  if (!ev) return <span className="badge">not sampled</span>;
  if (ev.status === 'pending' || ev.status === 'running')
    return <span className="badge info">evaluating…</span>;
  if (ev.status === 'skipped') return <span className="badge warn">not evaluated</span>;
  if (ev.status === 'error') return <span className="badge bad">evaluation failed</span>;
  return <span className="badge good">evaluated {fmtPct(ev.value)}</span>;
}

function TurnRow({
  turn,
  selected,
  onSelect,
}: {
  turn: AgentTurn;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        className={`turn-row${selected ? ' selected' : ''}`}
        onClick={onSelect}
        aria-current={selected}
      >
        <span className="row">
          <TurnBadge turn={turn} />
          <span className="muted small">{fmtDate(turn.ended_at)}</span>
        </span>
        <span className="small">{turn.input.slice(0, 100) || '(empty)'}</span>
        {turn.status === 'ok' && turn.latest_evaluation?.status === 'skipped' && (
          <span className="muted small">not evaluated - open for the reason</span>
        )}
      </button>
    </li>
  );
}

export default function AgentTurnsPanel({
  agentId,
  mode,
}: {
  agentId: number;
  mode: 'live' | 'conversations';
}) {
  const live = useAgentEvents(agentId, mode === 'live');
  const [sessionFilter, setSessionFilter] = useState('');
  const {
    data: turns,
    isLoading,
    error,
  } = useAgentTurns(agentId, mode === 'conversations' ? sessionFilter || null : null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { data: detail } = useAgentTurn(agentId, selectedId);

  const sessions = useMemo(
    () => [...new Set((turns ?? []).map((t) => t.session_id).filter((s): s is string => !!s))],
    [turns],
  );

  return (
    <div className="grid-2">
      <div>
        {mode === 'live' && (
          <p className="small muted" role="status">
            Live feed: {live.connection}
          </p>
        )}
        {mode === 'conversations' && sessions.length > 0 && (
          <div className="field">
            <label htmlFor="session-filter">Session</label>
            <select
              id="session-filter"
              value={sessionFilter}
              onChange={(e) => setSessionFilter(e.target.value)}
            >
              <option value="">All sessions</option>
              {sessions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        )}

        {isLoading && <Spinner label="Loading turns" />}
        {!!error && <ErrorBox error={error} title="Could not load turns." />}
        {turns && turns.length === 0 && (
          <Empty title="No turns yet">
            <p>Connect an agent with its ingest token to see its conversations here.</p>
          </Empty>
        )}
        {turns && turns.length > 0 && (
          <ul className="turn-list" aria-label="Turns">
            {turns.map((t) => (
              <TurnRow
                key={t.id}
                turn={t}
                selected={t.id === selectedId}
                onSelect={() => setSelectedId(t.id)}
              />
            ))}
          </ul>
        )}
      </div>
      <div>
        {!selectedId && <p className="muted">Select a turn to see its details.</p>}
        {selectedId && !detail && <Spinner label="Loading turn" />}
        {detail && <AgentTurnDrilldown agentId={agentId} turn={detail} />}
      </div>
    </div>
  );
}
