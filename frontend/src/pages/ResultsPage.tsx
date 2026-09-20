import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  ACTIVE_STATUSES,
  useModels,
  useResults,
  useRun,
  useRunActions,
  useRunMutations,
  useSummary,
} from '../api/hooks';
import type { JudgeMode, Weights } from '../api/types';
import { useRunEvents } from '../api/useRunEvents';
import CaseDrilldown from '../components/CaseDrilldown';
import ClassificationDetails from '../components/ClassificationDetails';
import JudgeStrictness from '../components/JudgeStrictness';
import Leaderboard from '../components/Leaderboard';
import WeightsPanel from '../components/WeightsPanel';
import ChartsSection from '../components/charts/ChartsSection';
import { Banner, Empty, ErrorBox, Spinner, StatusBadge } from '../components/ui';
import { fmtDate, fmtDuration } from '../lib/format';
import { EQUAL_WEIGHTS, withComposite } from '../lib/scores';

const MODE_LABEL: Record<JudgeMode, string> = {
  none: 'no judge',
  single: 'single judge',
  cross_model: 'cross-model judging',
};
/** Short description of how a run or attempt was judged, e.g. `judge qwen3:8b` or `cross-model judging`. */
function judgeLabel(mode: JudgeMode, model: string | null) {
  return mode === 'single' ? `judge ${model ?? '?'}` : MODE_LABEL[mode];
}

export default function ResultsPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [tab, setTab] = useState<'overview' | 'cases'>('overview');
  const [weights, setWeights] = useState<Weights>(EQUAL_WEIGHTS);
  const [includeCold, setIncludeCold] = useState(false);
  const [attempt, setAttempt] = useState<number | null>(null);
  const [judge, setJudge] = useState('');
  const [rescoreMode, setRescoreMode] = useState<JudgeMode>('none');

  const run = useRun(id);
  const busy = !!run.data && (ACTIVE_STATUSES.includes(run.data.status) || !!run.data.busy);
  useRunEvents(
    Number.isNaN(id) ? null : id,
    !!run.data?.busy && !ACTIVE_STATUSES.includes(run.data?.status ?? ''),
  );
  const hasRun = !!run.data;
  const summary = useSummary(id, { includeCold, attempt, enabled: hasRun });
  const results = useResults(id, attempt, hasRun);
  const models = useModels();
  const { rescore } = useRunActions(id);
  const { rerun } = useRunMutations();

  // Weights are applied here, instantly, with the same rule as the server (renormalised over scored categories).
  const rows = useMemo(
    () => withComposite(summary.data?.leaderboard ?? [], weights),
    [summary.data, weights],
  );

  const heading = <h1>Results</h1>;
  if (Number.isNaN(id))
    return (
      <>
        {heading}
        <Banner kind="error">Invalid run id.</Banner>
      </>
    );
  if (run.isLoading)
    return (
      <>
        {heading}
        <Spinner label="Loading run" />
      </>
    );
  if (run.error)
    return (
      <>
        {heading}
        <ErrorBox error={run.error} title="Could not load the run." />
      </>
    );
  const r = run.data!;
  const s = summary.data;
  const canCross = r.models.length >= 2;
  const attempts = s?.attempts ?? [];

  return (
    <>
      <div className="page-head">
        <div className="grow">
          {heading}
          <p className="muted">
            {r.name} <StatusBadge status={r.status} /> · {fmtDate(r.created_at)} ·{' '}
            {fmtDuration(r.started_at, r.finished_at)} · {r.models.length} models × {r.case_count}{' '}
            cases
            {r.parent_run_id && (
              <>
                {' '}
                · re-run of <Link to={`/runs/${r.parent_run_id}`}>#{r.parent_run_id}</Link>
              </>
            )}
          </p>
          <p className="small muted">
            temperature {r.config.temperature} · seed {r.config.seed} · {r.config.repeats} repeat
            {r.config.repeats > 1 ? 's' : ''} · ctx {r.config.num_ctx} ·{' '}
            {judgeLabel(
              s?.attempt?.judge_mode ?? r.judge_mode,
              s?.attempt ? s.attempt.judge_model : r.judge_model,
            )}
            {r.ollama_version ? ` · Ollama ${r.ollama_version}` : ''}
          </p>
        </div>
        <div className="row">
          <a className="btn" href={`/api/runs/${id}/export?format=csv`} download>
            Export CSV
          </a>
          <a className="btn" href={`/api/runs/${id}/export?format=json`} download>
            Export JSON
          </a>
          <button
            disabled={busy || rerun.isPending}
            onClick={() => rerun.mutate(id, { onSuccess: (n) => navigate(`/runs/${n.id}/live`) })}
          >
            Re-run
          </button>
        </div>
      </div>

      {rerun.error && <ErrorBox error={rerun.error} title="Could not re-run." />}
      {ACTIVE_STATUSES.includes(r.status) && (
        <Banner kind="info">
          This run is still in progress. <Link to={`/runs/${id}/live`}>Watch it live</Link>. Results
          below are partial.
        </Banner>
      )}
      {r.status === 'failed' && (
        <Banner kind="error">
          <strong>Run failed.</strong> {r.error} Completed results are shown.
        </Banner>
      )}
      {r.status === 'cancelled' && (
        <Banner kind="warn">This run was cancelled; results are partial.</Banner>
      )}
      {r.busy && !ACTIVE_STATUSES.includes(r.status) && (
        <Banner kind="info">
          <Spinner label="Re-scoring" /> Results refresh when scoring finishes.
        </Banner>
      )}
      {s && !s.comparable && (
        <Banner kind="info">
          Only one model was evaluated, so these are absolute scores. Run at least two models for a
          side-by-side comparison.
        </Banner>
      )}
      {s?.leaderboard.some((row) => row.self_judged) && (
        <Banner kind="warn">
          Some generation scores were judged by a model that is also being evaluated (marked
          “self-judged”). Models tend to favour their own output; consider re-scoring with
          cross-model judging or a different judge.
        </Banner>
      )}

      <div className="tabs" role="tablist" aria-label="Results view">
        <button role="tab" aria-selected={tab === 'overview'} onClick={() => setTab('overview')}>
          Overview
        </button>
        <button role="tab" aria-selected={tab === 'cases'} onClick={() => setTab('cases')}>
          Cases
        </button>
      </div>

      {tab === 'overview' && (
        <>
          {summary.isLoading && <Spinner label="Loading summary" />}
          {summary.error && <ErrorBox error={summary.error} title="Could not load the summary." />}
          {s && rows.length === 0 && <Empty title="No results yet" />}
          {s && rows.length > 0 && (
            <>
              <section
                className="card"
                aria-label="Leaderboard"
                style={{ opacity: summary.isPlaceholderData ? 0.6 : 1 }}
              >
                <div className="card-head">
                  <h2>Leaderboard</h2>
                  <span className="spacer" />
                  <label className="check" style={{ fontWeight: 400 }}>
                    <input
                      type="checkbox"
                      checked={includeCold}
                      onChange={(e) => setIncludeCold(e.target.checked)}
                    />
                    <span>Include cold-start requests in speed figures</span>
                  </label>
                </div>
                <WeightsPanel
                  weights={weights}
                  onChange={setWeights}
                  present={s.categories_present}
                />
                <Leaderboard rows={rows} judgeMode={s.judging.mode} />
                <p className="small muted" style={{ marginTop: 8 }}>
                  Speed figures use warm requests only; model load time is reported separately.
                  Scores show scored/total cases; unscored cases are excluded, failed requests count
                  as 0.
                </p>
              </section>
              <JudgeStrictness mode={s.judging.mode} judges={s.judging.judges} />
              <ClassificationDetails rows={rows} />
              <div style={{ marginTop: 16 }}>
                <ChartsSection rows={rows} categories={s.categories_present} />
              </div>
            </>
          )}

          {s && (
            <section className="card" aria-label="Scoring" style={{ marginTop: 16 }}>
              <h2>Scoring</h2>
              <div className="row">
                {attempts.length > 1 && (
                  <div className="field" style={{ margin: 0 }}>
                    <label htmlFor="attempt">Scoring attempt</label>
                    <select
                      id="attempt"
                      value={attempt ?? s.attempt?.id ?? ''}
                      onChange={(e) => setAttempt(Number(e.target.value))}
                    >
                      {attempts.map((a) => (
                        <option key={a.id} value={a.id}>
                          #{a.id} · {judgeLabel(a.judge_mode, a.judge_model)}
                          {a.id === attempts[attempts.length - 1].id ? ' (latest)' : ''}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                <div className="field" style={{ margin: 0 }}>
                  <label htmlFor="rescore-mode">Re-score with</label>
                  <select
                    id="rescore-mode"
                    value={rescoreMode}
                    onChange={(e) => setRescoreMode(e.target.value as JudgeMode)}
                    aria-describedby={canCross ? undefined : 'rescore-cross-hint'}
                  >
                    <option value="none">No judge</option>
                    <option value="single">Single judge model</option>
                    <option value="cross_model" disabled={!canCross}>
                      Cross-model judging
                    </option>
                  </select>
                </div>
                {rescoreMode === 'single' && (
                  <div className="field" style={{ margin: 0 }}>
                    <label htmlFor="rejudge">Judge model</label>
                    <select id="rejudge" value={judge} onChange={(e) => setJudge(e.target.value)}>
                      <option value="">Choose a judge…</option>
                      {(models.data ?? []).map((m) => (
                        <option key={m.name} value={m.name}>
                          {m.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                <button
                  style={{ alignSelf: 'flex-end' }}
                  disabled={busy || rescore.isPending || (rescoreMode === 'single' && !judge)}
                  onClick={() =>
                    rescore.mutate(
                      {
                        judge_mode: rescoreMode,
                        judge_model: rescoreMode === 'single' ? judge : null,
                      },
                      { onSuccess: () => setAttempt(null) },
                    )
                  }
                >
                  Re-score
                </button>
              </div>
              {!canCross && (
                <p id="rescore-cross-hint" className="small muted" style={{ margin: '8px 0 0' }}>
                  Cross-model judging is unavailable: this run evaluated only one model.
                </p>
              )}
              <p className="small muted" style={{ margin: '8px 0 0' }}>
                Re-scoring never regenerates outputs or changes performance numbers; earlier
                attempts stay available.
              </p>
              {rescore.error && <ErrorBox error={rescore.error} title="Could not re-score." />}
            </section>
          )}
        </>
      )}

      {tab === 'cases' && (
        <>
          {results.isLoading && <Spinner label="Loading results" />}
          {results.error && <ErrorBox error={results.error} title="Could not load results." />}
          {results.data && <CaseDrilldown run={r} results={results.data.results} />}
        </>
      )}
    </>
  );
}
