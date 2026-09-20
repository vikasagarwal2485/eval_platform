import type { JudgeStat, JudgeMode } from '../api/types';
import { dash, fmtPct } from '../lib/format';

/** Average score each judge gave: a quick check for a much harsher or more lenient judge. */
export default function JudgeStrictness({
  mode,
  judges,
}: {
  mode: JudgeMode;
  judges: JudgeStat[];
}) {
  if (!judges.length) return null;
  const hasReasoning = judges.some((j) => j.reasoning_mean_score !== null);
  return (
    <section className="card" aria-labelledby="strict-h" style={{ marginTop: 16 }}>
      <h2 id="strict-h">Judge strictness</h2>
      <p className="small muted">
        {mode === 'cross_model'
          ? 'Each model was judged only by the others, and judges scored different answers, so these averages are a rough check: a judge far below the rest may be unusually harsh, one far above unusually lenient. Scores from different judges are not perfectly like-for-like.'
          : 'How this judge scored the answers it was given.'}
      </p>
      <div className="table-wrap">
        <table aria-label="Judge strictness">
          <thead>
            <tr>
              <th>Judge</th>
              <th className="num">Answers judged</th>
              <th className="num">Failed</th>
              <th className="num">Average score given</th>
              {hasReasoning && <th className="num">Average reasoning score</th>}
            </tr>
          </thead>
          <tbody>
            {judges.map((j) => (
              <tr key={j.model}>
                <td>
                  <strong>{j.model}</strong>
                </td>
                <td className="num">{j.judged}</td>
                <td className="num">
                  {j.errors > 0 ? <span className="badge bad">{j.errors} failed</span> : 0}
                </td>
                <td className="num">{j.mean_score === null ? dash : fmtPct(j.mean_score, 1)}</td>
                {hasReasoning && (
                  <td className="num">
                    {j.reasoning_mean_score === null ? dash : fmtPct(j.reasoning_mean_score, 1)}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
