import { useState } from 'react';
import type { AgentEvaluation, AgentJudgement, AgentTurnDetail } from '../../api/types';
import { useEvaluateTurn } from '../../api/hooks';
import { fmtDate, fmtMs, fmtPct } from '../../lib/format';
import { OutcomeBadge } from '../ui';

function CriteriaList({
  criteria,
}: {
  criteria: Record<string, { score: number; reason: string }> | undefined;
}) {
  const entries = Object.entries(criteria ?? {});
  if (!entries.length) return null;
  return (
    <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
      {entries.map(([name, c]) => (
        <li key={name}>
          <strong>{name}</strong> {c.score}/5 <span className="muted">{c.reason}</span>
        </li>
      ))}
    </ul>
  );
}

const SKIP_REASON_TEXT: Record<string, string> = {
  no_eligible_evaluator:
    'No configured evaluator is eligible - every one produced (part of) this turn.',
  agent_model_unknown: "The turn's model could not be determined, so it was not evaluated.",
  backlog: 'Skipped: the evaluation backlog exceeded its limit.',
};

/** One evaluation attempt: overall score, and each evaluator's own criteria and reasons (per-judge breakdown,
 * matching the style of the benchmark-run drill-down's cross-model judge block). */
function EvaluationBlock({ evaluation, open }: { evaluation: AgentEvaluation; open?: boolean }) {
  if (evaluation.status === 'pending' || evaluation.status === 'running')
    return <div className="muted">Evaluation {evaluation.status}…</div>;
  if (evaluation.status === 'skipped')
    return (
      <div className="muted">
        Not evaluated: {SKIP_REASON_TEXT[evaluation.skip_reason ?? ''] ?? evaluation.skip_reason}
      </div>
    );

  const judgements = evaluation.detail.judgements ?? [];
  const ok = judgements.filter((j) => j.outcome === 'judged').length;
  return (
    <details open={open || evaluation.status === 'error'}>
      <summary>
        Attempt {evaluation.attempt_no}:{' '}
        {evaluation.status === 'done' ? fmtPct(evaluation.value) : 'all evaluators failed'}
        {judgements.length > 1 ? ` · ${ok} of ${judgements.length} evaluators judged` : ''}
        {evaluation.detail.self_judged ? ' · self-judged' : ''}
      </summary>
      <ul style={{ margin: '4px 0', paddingLeft: 18 }} aria-label="By evaluator">
        {judgements.map((j: AgentJudgement) => (
          <li key={j.judge_model}>
            <strong>{j.judge_model}</strong>{' '}
            {j.outcome === 'judged' ? fmtPct(j.value) : <span className="badge bad">failed</span>}{' '}
            {j.outcome === 'error' && <span className="muted">{j.detail.error}</span>}
            <CriteriaList criteria={j.detail.criteria} />
          </li>
        ))}
      </ul>
      {evaluation.reference_result && (
        <div className="small">
          Reference correctness: <OutcomeBadge outcome={evaluation.reference_result.outcome} />
        </div>
      )}
    </details>
  );
}

export default function AgentTurnDrilldown({
  agentId,
  turn,
}: {
  agentId: number;
  turn: AgentTurnDetail;
}) {
  const [evaluators, setEvaluators] = useState('');
  const evaluate = useEvaluateTurn(agentId);
  const evaluations = [...turn.evaluations].reverse(); // latest first

  return (
    <div>
      <div className="row" style={{ marginBottom: 4 }}>
        <OutcomeBadge outcome={turn.status === 'ok' ? 'pass' : turn.status} />
        <span className="muted small">{fmtDate(turn.ended_at)}</span>
        <span className="spacer" />
        <span className="muted small">{fmtMs(turn.latency_ms)}</span>
      </div>

      <div className="small">
        <strong>Input</strong>
        <pre className="output">{turn.input || '(empty)'}</pre>
      </div>
      <div className="small">
        <strong>Output</strong>
        <pre className="output">
          {turn.output || (turn.status === 'error' ? '(no output)' : '(empty)')}
        </pre>
      </div>
      {turn.error && <div className="field-error">Error: {turn.error}</div>}
      {turn.reference && (
        <div className="small">
          Reference: <code>{turn.reference}</code>
        </div>
      )}

      <details>
        <summary>Spans ({turn.spans.length})</summary>
        {turn.spans.map((s) => (
          <div key={s.id} className="small" style={{ marginBottom: 8 }}>
            <div className="row">
              <span className="badge">{s.kind}</span>
              {s.model && <code>{s.model}</code>}
              {s.name && <code>{s.name}</code>}
              <span className="muted">{fmtMs(s.latency_ms)}</span>
            </div>
            {s.thinking && (
              <details>
                <summary>Reasoning</summary>
                <pre className="output">{s.thinking}</pre>
              </details>
            )}
            <pre className="output">{s.output || s.error || '(no output)'}</pre>
          </div>
        ))}
      </details>

      <h2 style={{ margin: '12px 0 4px', fontSize: '1rem' }}>Evaluation</h2>
      {evaluations.length === 0 && <div className="muted">Not evaluated yet.</div>}
      {evaluations.map((e, i) => (
        <EvaluationBlock key={e.id} evaluation={e} open={i === 0} />
      ))}

      {turn.status === 'ok' && (
        <div className="row" style={{ marginTop: 8 }}>
          <input
            aria-label="Evaluators for re-evaluation (comma-separated, optional)"
            placeholder="Evaluators (comma-separated; leave blank to reuse the agent's current ones)"
            value={evaluators}
            onChange={(e) => setEvaluators(e.target.value)}
            style={{ minWidth: 320 }}
          />
          <button
            type="button"
            onClick={() =>
              evaluate.mutate({
                turnId: turn.id,
                evaluators: evaluators.trim()
                  ? evaluators
                      .split(',')
                      .map((s) => s.trim())
                      .filter(Boolean)
                  : undefined,
              })
            }
            disabled={evaluate.isPending}
          >
            {evaluate.isPending ? 'Re-evaluating…' : 'Re-evaluate'}
          </button>
        </div>
      )}
    </div>
  );
}
