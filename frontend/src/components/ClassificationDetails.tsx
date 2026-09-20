import type { LeaderRow } from '../api/types';
import { dash, fmtPct } from '../lib/format';

export default function ClassificationDetails({ rows }: { rows: LeaderRow[] }) {
  const withCls = rows.filter((r) => r.classification && r.classification.n > 0);
  if (!withCls.length) return null;
  return (
    <section className="card" aria-labelledby="cls-h" style={{ marginTop: 16 }}>
      <h2 id="cls-h">Classification details</h2>
      <p className="small muted">
        Accuracy counts unparseable answers as wrong. Precision, recall and F1 are per label across
        all classification cases; the confusion matrix reads expected (rows) against predicted
        (columns).
      </p>
      <div className="grid-2">
        {withCls.map((r) => {
          const c = r.classification!;
          return (
            <div key={r.model}>
              <h3>
                {r.model}{' '}
                <span className="badge">
                  accuracy {fmtPct(c.accuracy)} ({c.n} cases)
                </span>
                {c.unparseable > 0 && (
                  <span className="badge warn" style={{ marginLeft: 4 }}>
                    {c.unparseable} unparseable
                  </span>
                )}
              </h3>
              <div className="table-wrap">
                <table aria-label={`Per-label metrics for ${r.model}`}>
                  <thead>
                    <tr>
                      <th>Label</th>
                      <th className="num">Precision</th>
                      <th className="num">Recall</th>
                      <th className="num">F1</th>
                      <th className="num">Support</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(c.per_label).map(([label, m]) => (
                      <tr key={label}>
                        <td>{label}</td>
                        <td className="num">{m.precision === null ? dash : fmtPct(m.precision)}</td>
                        <td className="num">{m.recall === null ? dash : fmtPct(m.recall)}</td>
                        <td className="num">{m.f1 === null ? dash : fmtPct(m.f1)}</td>
                        <td className="num">{m.support}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {c.confusion && (
                <div className="table-wrap" style={{ marginTop: 8 }}>
                  <table aria-label={`Confusion matrix for ${r.model}`}>
                    <thead>
                      <tr>
                        <th>expected ↓ / predicted →</th>
                        {c.confusion.labels.map((l) => (
                          <th key={l} className="num">
                            {l}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(c.confusion.rows).map(([exp, cols]) => (
                        <tr key={exp}>
                          <th scope="row">{exp}</th>
                          {c.confusion!.labels.map((l) => (
                            <td key={l} className="num">
                              {cols[l] ?? 0}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
