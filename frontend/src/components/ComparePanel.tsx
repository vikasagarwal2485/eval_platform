import { useCompare } from '../api/hooks';
import type { Delta } from '../api/types';
import { dash, fmtMs, fmtNum, fmtPct, titleCase } from '../lib/format';
import { ErrorBox, Spinner } from './ui';

/** Signed change with an arrow and a word, so direction is never colour alone. */
function DeltaCell({ d, kind }: { d: Delta | undefined; kind: 'pct' | 'ms' | 'num' }) {
  if (!d || d.delta === null) return <>{dash}</>;
  const fmt = (v: number | null) =>
    kind === 'pct' ? fmtPct(v, 1) : kind === 'ms' ? fmtMs(v) : fmtNum(v);
  const zero = Math.abs(d.delta) < 1e-9;
  const up = d.delta > 0;
  const change =
    kind === 'pct'
      ? `${up ? '+' : '−'}${Math.abs(d.delta * 100).toFixed(1)} pts`
      : kind === 'ms'
        ? `${up ? '+' : '−'}${fmtMs(Math.abs(d.delta))}`
        : `${up ? '+' : '−'}${fmtNum(Math.abs(d.delta))}`;
  return (
    <span>
      {fmt(d.a)} → {fmt(d.b)}{' '}
      <strong
        className="small"
        aria-label={zero ? 'no change' : up ? `up ${change}` : `down ${change}`}
      >
        {zero ? '＝ no change' : `${up ? '▲' : '▼'} ${change}`}
      </strong>
    </span>
  );
}

export default function ComparePanel({ a, b }: { a: number; b: number }) {
  const { data, isLoading, error } = useCompare(a, b);
  if (isLoading) return <Spinner label="Comparing runs" />;
  if (error || !data) return <ErrorBox error={error} title="Could not compare." />;
  return (
    <section className="card" aria-label="Run comparison">
      <h2>
        Run #{data.a.id} → Run #{data.b.id}
      </h2>
      <p className="muted small">
        Changes from {data.a.name} to {data.b.name}, for models and cases present in both. Scores
        are in percentage points.
      </p>
      {data.models.length === 0 && <p>No models in common between these runs.</p>}
      {data.models.length > 0 && (
        <div className="table-wrap">
          <table aria-label="Model changes">
            <thead>
              <tr>
                <th>Model</th>
                <th>Composite</th>
                {['classification', 'reasoning', 'generation'].map((c) => (
                  <th key={c}>{titleCase(c)}</th>
                ))}
                <th>Median latency</th>
                <th>Tokens/s</th>
              </tr>
            </thead>
            <tbody>
              {data.models.map((m) => (
                <tr key={m.model}>
                  <td>
                    <strong>{m.model}</strong>
                    {!m.same_digest && (
                      <div>
                        <span className="badge warn" title="The model files changed between runs">
                          different build
                        </span>
                      </div>
                    )}
                  </td>
                  <td>
                    <DeltaCell d={m.composite} kind="pct" />
                  </td>
                  {(['classification', 'reasoning', 'generation'] as const).map((c) => (
                    <td key={c}>
                      <DeltaCell d={m.categories[c]} kind="pct" />
                    </td>
                  ))}
                  <td>
                    <DeltaCell d={m.performance.latency_ms} kind="ms" />
                  </td>
                  <td>
                    <DeltaCell d={m.performance.tokens_per_s} kind="num" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(data.only_in_a.length > 0 || data.only_in_b.length > 0) && (
        <p className="small muted">
          {data.only_in_a.length > 0 && (
            <>
              Only in run #{data.a.id}: {data.only_in_a.join(', ')}.{' '}
            </>
          )}
          {data.only_in_b.length > 0 && (
            <>
              Only in run #{data.b.id}: {data.only_in_b.join(', ')}.
            </>
          )}
        </p>
      )}
      {data.cases.some((c) => c.delta !== null && Math.abs(c.delta) > 1e-9) && (
        <details style={{ marginTop: 8 }}>
          <summary>Cases that changed</summary>
          <div className="table-wrap">
            <table aria-label="Case changes">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Case</th>
                  <th>Change</th>
                </tr>
              </thead>
              <tbody>
                {data.cases
                  .filter((c) => c.delta !== null && Math.abs(c.delta) > 1e-9)
                  .map((c, i) => (
                    <tr key={i}>
                      <td>{c.model}</td>
                      <td>{c.title}</td>
                      <td>
                        <DeltaCell d={{ a: c.a, b: c.b, delta: c.delta }} kind="pct" />
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}
