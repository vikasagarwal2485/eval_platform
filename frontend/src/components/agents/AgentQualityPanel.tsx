import { useState } from 'react';
import { useAgentAttention, useAgentSummary } from '../../api/hooks';
import { dash, fmtMs, fmtPct } from '../../lib/format';
import { Empty, ErrorBox, Spinner } from '../ui';

const WINDOWS = [
  { value: '1h', label: 'Last hour' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
];

export default function AgentQualityPanel({ agentId }: { agentId: number }) {
  const [window, setWindow] = useState('24h');
  const { data: summary, isLoading, error } = useAgentSummary(agentId, window);
  const { data: attention } = useAgentAttention(agentId, window);

  return (
    <div className="stack">
      <div className="row">
        <div className="field" style={{ margin: 0 }}>
          <label htmlFor="quality-window">Window</label>
          <select id="quality-window" value={window} onChange={(e) => setWindow(e.target.value)}>
            {WINDOWS.map((w) => (
              <option key={w.value} value={w.value}>
                {w.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {isLoading && <Spinner label="Loading quality figures" />}
      {!!error && <ErrorBox error={error} title="Could not load the summary." />}

      {summary && (
        <>
          <section className="card">
            <h2>Overview</h2>
            <div className="grid-2">
              <div>
                <div className="muted small">Quality (mean)</div>
                <div style={{ fontSize: '1.5rem' }}>{fmtPct(summary.quality.mean)}</div>
                <div className="small muted">
                  {summary.quality.evaluated} evaluated · {summary.quality.below_threshold} below
                  threshold
                </div>
              </div>
              <div>
                <div className="muted small">Latency</div>
                <div style={{ fontSize: '1.5rem' }}>{fmtMs(summary.latency_ms.p95)} p95</div>
                <div className="small muted">p50 {fmtMs(summary.latency_ms.p50)}</div>
              </div>
              <div>
                <div className="muted small">Error rate</div>
                <div style={{ fontSize: '1.5rem' }}>{fmtPct(summary.error_rate)}</div>
                <div className="small muted">{summary.turns.total} turns</div>
              </div>
              <div>
                <div className="muted small">Tokens</div>
                <div style={{ fontSize: '1.5rem' }}>{summary.tokens.completion}</div>
                <div className="small muted">{summary.tokens.prompt} prompt</div>
              </div>
            </div>
            {summary.backlog.pending > 0 && (
              <p className="small muted">{summary.backlog.pending} evaluations pending.</p>
            )}
          </section>

          <section className="card">
            <h2>Quality over time</h2>
            {summary.series.length === 0 ? (
              <p className="muted small">No turns in this window yet.</p>
            ) : (
              <table>
                <caption className="sr-only">Turn count and mean quality per time bucket</caption>
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Turns</th>
                    <th scope="col">Mean quality</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.series.map((p) => (
                    <tr key={p.bucket}>
                      <td>{p.bucket}</td>
                      <td>{p.count}</td>
                      <td>{fmtPct(p.quality_mean)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card">
            <h2>Evaluator strictness</h2>
            {summary.evaluators.length === 0 ? (
              <p className="muted small">No evaluations yet.</p>
            ) : (
              <table>
                <caption className="sr-only">Average score and error count per evaluator</caption>
                <thead>
                  <tr>
                    <th scope="col">Evaluator</th>
                    <th scope="col">Average score</th>
                    <th scope="col">Judged</th>
                    <th scope="col">Errors</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.evaluators.map((e) => (
                    <tr key={e.model}>
                      <td>
                        <code>{e.model}</code>
                      </td>
                      <td>{fmtPct(e.mean_score)}</td>
                      <td>{e.judged}</td>
                      <td>{e.errors}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card" aria-labelledby="attention-h">
            <h2 id="attention-h">Needs attention</h2>
            {!attention || attention.length === 0 ? (
              <Empty title="Nothing below the threshold right now" />
            ) : (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {attention.map((a) => (
                  <li key={a.turn_id}>
                    <strong>{fmtPct(a.value)}</strong> - {a.input?.slice(0, 80) || dash}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
