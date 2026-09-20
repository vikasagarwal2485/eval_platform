import { useMemo, useState } from 'react';
import type { Category, Judgement, ResultItem, Run, RunCase, ScoreRow } from '../api/types';
import { CATEGORIES } from '../api/types';
import { dash, fmtMs, fmtNum, fmtPct } from '../lib/format';
import { CategoryBadge, Empty, OutcomeBadge } from './ui';

const FAILURES = ['wrong', 'unparseable', 'error'];

type Criteria = Record<string, { score: number; reason: string }>;

function CriteriaList({ criteria }: { criteria: Criteria | undefined }) {
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

/** A judged score: one judge (criteria inline) or, for cross-model judging, every judge's own verdict. */
function JudgeBlock({ score, label, open }: { score: ScoreRow; label: string; open?: boolean }) {
  const cross = score.detail.mode === 'cross_model';
  const judgements = (score.detail.judgements ?? []) as Judgement[];
  if (score.outcome === 'unscored') return <div className="muted">Unscored (no judge model).</div>;

  if (!cross) {
    if (score.outcome === 'error')
      return <div className="muted">Judge failed: {String(score.detail.error)}</div>;
    return (
      <details open={open}>
        <summary>
          {label}: {fmtPct(score.value)}
          {score.detail.self_judged ? ' · self-judged' : ''}
        </summary>
        <CriteriaList criteria={score.detail.criteria as Criteria | undefined} />
      </details>
    );
  }

  const ok = judgements.filter((j) => j.outcome === 'judged').length;
  return (
    <details open={open || score.outcome === 'error'}>
      <summary>
        {label}: {score.outcome === 'judged' ? fmtPct(score.value) : 'all judges failed'} ·
        cross-judged by {ok} of {judgements.length} {judgements.length === 1 ? 'judge' : 'judges'}
      </summary>
      <ul style={{ margin: '4px 0', paddingLeft: 18 }} aria-label={`${label} by judge`}>
        {judgements.map((j) => (
          <li key={j.judge_model}>
            <strong>{j.judge_model}</strong>{' '}
            {j.outcome === 'judged' ? fmtPct(j.value) : <span className="badge bad">failed</span>}{' '}
            {j.outcome === 'error' && <span className="muted">{j.error}</span>}
            <CriteriaList criteria={j.criteria} />
          </li>
        ))}
      </ul>
    </details>
  );
}

function ScoreDetails({ r }: { r: ResultItem }) {
  const auto = r.scores.find((s) => s.kind === 'auto');
  const judge = r.scores.find((s) => s.kind === 'judge');
  const cons = r.scores.find((s) => s.kind === 'constraints');
  const reasoning = r.scores.find((s) => s.kind === 'judge_reasoning');
  const d = auto?.detail ?? {};
  return (
    <div className="small">
      {r.category === 'classification' && !!auto && (
        <div>
          Predicted: <code>{String(d.predicted ?? dash)}</code>
          {d.ambiguous ? (
            <span className="badge warn" style={{ marginLeft: 4 }}>
              ambiguous
            </span>
          ) : null}
        </div>
      )}
      {r.category === 'reasoning' && !!auto && (
        <div>
          Final answer: <code>{String(d.final_answer ?? dash)}</code>{' '}
          <span className="muted">({String(d.method)})</span>
        </div>
      )}
      {cons && (
        <div>
          Constraints: <OutcomeBadge outcome={cons.outcome} />{' '}
          {(
            (cons.detail.checks ?? []) as {
              name: string;
              passed: boolean;
              keyword?: string;
              actual?: number;
              limit?: number;
            }[]
          )
            .filter((c) => !c.passed)
            .map((c) => (
              <span key={c.name + (c.keyword ?? '')} className="muted">
                {c.name}
                {c.keyword ? ` "${c.keyword}"` : ` ${c.actual}/${c.limit}`}{' '}
              </span>
            ))}
        </div>
      )}
      {judge && <JudgeBlock score={judge} label="Judge" open />}
      {reasoning && reasoning.outcome !== 'unscored' && (
        <JudgeBlock score={reasoning} label="Reasoning quality" />
      )}
    </div>
  );
}

function Metrics({ r }: { r: ResultItem }) {
  const m = r.metrics as Record<string, number | boolean | null>;
  const think = m.thinking_tokens as number | null | undefined;
  return (
    <div className="small muted">
      {fmtMs(r.latency_ms)} · TTFT {fmtMs(r.ttft_ms)} · {fmtNum(r.tokens_per_s)} tok/s ·{' '}
      {r.output_tokens ?? dash} tokens
      {think ? ` (${m.thinking_tokens_approx ? '~' : ''}${think} thinking)` : ''}
      {r.is_cold && (
        <span className="badge warn" style={{ marginLeft: 4 }}>
          cold start
        </span>
      )}
    </div>
  );
}

function ModelResult({ r, multi }: { r: ResultItem; multi: boolean }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="row" style={{ marginBottom: 4 }}>
        {multi && <span className="muted small">Repeat {r.repeat + 1}</span>}
        <OutcomeBadge outcome={r.primary.outcome} value={r.primary.value} />
      </div>
      {r.status === 'error' && <div className="field-error">Error: {r.error}</div>}
      <pre className="output">
        {r.output || (r.status === 'error' ? '(no output)' : '(empty answer)')}
      </pre>
      {r.thinking && (
        <details>
          <summary>Reasoning trace ({r.thinking.length} chars)</summary>
          <pre className="output">{r.thinking}</pre>
        </details>
      )}
      <ScoreDetails r={r} />
      <Metrics r={r} />
    </div>
  );
}

export default function CaseDrilldown({ run, results }: { run: Run; results: ResultItem[] }) {
  const [category, setCategory] = useState<Category | ''>('');
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [model, setModel] = useState('');
  const models = run.models.map((m) => m.name);

  const byCase = useMemo(() => {
    const map = new Map<number, Map<string, ResultItem[]>>();
    for (const r of results) {
      const perModel = map.get(r.case_id) ?? new Map<string, ResultItem[]>();
      perModel.set(r.model, [...(perModel.get(r.model) ?? []), r]);
      map.set(r.case_id, perModel);
    }
    return map;
  }, [results]);

  const visible = (run.cases ?? []).filter((c: RunCase) => {
    if (category && c.category !== category) return false;
    if (!failuresOnly) return true;
    const scope = model ? [model] : models;
    return scope.some((m) =>
      (byCase.get(c.id)?.get(m) ?? []).some((r) => FAILURES.includes(r.primary.outcome)),
    );
  });

  return (
    <div>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row">
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="f-cat">Category</label>
            <select
              id="f-cat"
              value={category}
              onChange={(e) => setCategory(e.target.value as Category | '')}
            >
              <option value="">All</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="f-model">Model</label>
            <select id="f-model" value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">All models</option>
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <label className="check" style={{ alignSelf: 'flex-end', paddingBottom: 6 }}>
            <input
              type="checkbox"
              checked={failuresOnly}
              onChange={(e) => setFailuresOnly(e.target.checked)}
            />
            <span>Only cases {model || 'a model'} got wrong, could not parse, or errored on</span>
          </label>
          <span className="spacer" />
          <span className="muted small" aria-live="polite">
            {visible.length} of {run.cases?.length ?? 0} cases
          </span>
        </div>
      </div>

      {visible.length === 0 && (
        <Empty title="No matching cases">
          {failuresOnly ? 'Nothing failed for this selection.' : 'Adjust the filters.'}
        </Empty>
      )}

      {visible.map((c) => {
        const perModel = byCase.get(c.id);
        const sent = [...(perModel?.values() ?? [])][0]?.[0];
        const shown = model ? [model] : models;
        return (
          <section
            key={c.id}
            className="card"
            aria-label={`Case: ${c.title || c.prompt.slice(0, 40)}`}
          >
            <div className="card-head">
              <h2 style={{ margin: 0, fontSize: '1.05rem' }}>{c.title || c.prompt.slice(0, 80)}</h2>
              <CategoryBadge category={c.category} />
              {c.expected && (
                <span className="small">
                  Expected: <code>{c.expected}</code>
                </span>
              )}
            </div>
            <details>
              <summary>Prompt</summary>
              <pre className="output">{c.prompt}</pre>
              {sent && (
                <p className="small muted">
                  Sent to models (template {sent.template_version}, with the answer-format
                  instruction appended):
                </p>
              )}
              {sent && <pre className="output">{sent.sent_prompt}</pre>}
            </details>
            <div className="grid-2" style={{ marginTop: 12 }}>
              {shown.map((m) => {
                const rs = perModel?.get(m) ?? [];
                return (
                  <div key={m}>
                    <h3 style={{ margin: '0 0 6px' }}>{m}</h3>
                    {rs.length === 0 && <p className="muted small">No result.</p>}
                    {rs.map((r) => (
                      <ModelResult key={r.id} r={r} multi={rs.length > 1} />
                    ))}
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}
