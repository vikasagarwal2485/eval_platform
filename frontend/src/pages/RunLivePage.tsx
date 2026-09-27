import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ACTIVE_STATUSES, useResults, useRun, useRunActions } from '../api/hooks';
import { useRunEvents } from '../api/useRunEvents';
import ModelChip from '../components/ModelChip';
import { Banner, ErrorBox, OutcomeBadge, Spinner, StatusBadge } from '../components/ui';
import { fmtMs, fmtNum } from '../lib/format';

interface Row {
  id: number;
  model: string;
  caseId: number;
  repeat: number;
  status: string;
  outcome: string | null;
  value: number | null;
  latency: number | null;
  tps: number | null;
  cold: boolean;
}

export default function RunLivePage() {
  const id = Number(useParams().id);
  const run = useRun(id);
  const active = !!run.data && (ACTIVE_STATUSES.includes(run.data.status) || !!run.data.busy);
  const live = useRunEvents(Number.isNaN(id) ? null : id, active);
  const results = useResults(id, null, !!run.data);
  const { cancel } = useRunActions(id);

  const cases = useMemo(
    () => new Map((run.data?.cases ?? []).map((c) => [c.id, c])),
    [run.data?.cases],
  );
  const modelInfo = useMemo(
    () => new Map((run.data?.models ?? []).map((m) => [m.name, m])),
    [run.data?.models],
  );

  // DB rows are the source of truth; SSE events show up instantly until the refetch lands.
  const rows = useMemo(() => {
    const byId = new Map<number, Row>();
    for (const e of live.results)
      byId.set(e.result_id, {
        id: e.result_id,
        model: e.model,
        caseId: e.case_id,
        repeat: e.repeat,
        status: e.status,
        outcome: e.outcome,
        value: e.value,
        latency: e.latency_ms,
        tps: e.tokens_per_s,
        cold: e.is_cold,
      });
    for (const r of results.data?.results ?? [])
      byId.set(r.id, {
        id: r.id,
        model: r.model,
        caseId: r.case_id,
        repeat: r.repeat,
        status: r.status,
        outcome: r.primary.outcome,
        value: r.primary.value,
        latency: r.latency_ms,
        tps: r.tokens_per_s,
        cold: r.is_cold,
      });
    return [...byId.values()].sort((a, b) => a.id - b.id);
  }, [live.results, results.data]);

  const heading = <h1>Live run</h1>;
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

  const dbProgress = r.progress;
  const progress =
    live.progress && live.progress.completed > dbProgress.completed ? live.progress : dbProgress;
  const pct = progress.total ? Math.round((progress.completed / progress.total) * 100) : 0;
  const current = { ...r.current, ...live.current };
  const finished = !active;
  const scoring = live.scoring && !live.finished ? live.scoring : null;

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>Live run</h1>
          <p className="muted">
            {r.name} <StatusBadge status={r.status} />{' '}
            {live.connection === 'reconnecting' && (
              <span className="badge warn">reconnecting…</span>
            )}
          </p>
        </div>
        {active && (
          <button
            className="danger"
            onClick={() => cancel.mutate()}
            disabled={cancel.isPending || cancel.isSuccess}
          >
            {cancel.isPending || cancel.isSuccess ? 'Cancelling…' : 'Cancel run'}
          </button>
        )}
        {finished && r.status !== 'queued' && (
          <Link className="btn primary" to={`/runs/${r.id}`} style={{ textDecoration: 'none' }}>
            <button className="primary" type="button">
              View results
            </button>
          </Link>
        )}
      </div>

      {cancel.error && <ErrorBox error={cancel.error} title="Could not cancel." />}
      {r.status === 'failed' && (
        <Banner kind="error">
          <strong>Run failed.</strong> {r.error}
        </Banner>
      )}
      {r.status === 'cancelled' && (
        <Banner kind="warn">Run cancelled. Completed results are kept and can be viewed.</Banner>
      )}
      {live.warnings.map((w) => (
        <Banner kind="warn" key={w}>
          {w}
        </Banner>
      ))}

      <section className="card" aria-label="Progress">
        <div className="row" style={{ marginBottom: 8 }}>
          <strong>
            {progress.completed} / {progress.total}
          </strong>
          <span className="muted">requests</span>
          <span className="spacer" />
          <span>{pct}%</span>
        </div>
        <div
          className="progress"
          role="progressbar"
          aria-label="Run progress"
          aria-valuemin={0}
          aria-valuemax={progress.total}
          aria-valuenow={progress.completed}
        >
          <div style={{ width: `${pct}%` }} />
        </div>
        {active && (
          <p className="small" style={{ margin: '10px 0 0' }} aria-live="polite">
            {r.status === 'queued' && !current.model ? (
              'Waiting for the run queue…'
            ) : scoring ? (
              `Scoring generated answers with the judge… ${scoring.done}/${scoring.total || '?'}`
            ) : current.model ? (
              <>
                Running{' '}
                <ModelChip
                  name={current.model}
                  source={modelInfo.get(current.model)?.source}
                  provider={modelInfo.get(current.model)?.provider}
                  providerKind={modelInfo.get(current.model)?.provider_kind}
                />{' '}
                · {current.case_title ?? `case ${current.case_id}`}
                {current.repeat ? ` (repeat ${current.repeat + 1})` : ''}
              </>
            ) : (
              'Starting…'
            )}
          </p>
        )}
      </section>

      {active && live.preview && (
        <section className="card" aria-label="Streaming preview">
          <h2>
            Streaming:{' '}
            <ModelChip
              name={live.preview.model}
              source={modelInfo.get(live.preview.model)?.source}
              provider={modelInfo.get(live.preview.model)?.provider}
              providerKind={modelInfo.get(live.preview.model)?.provider_kind}
            />
          </h2>
          {live.preview.thinking && (
            <details>
              <summary>Thinking ({live.preview.thinking.length} chars)</summary>
              <pre className="output">{live.preview.thinking}</pre>
            </details>
          )}
          <pre className="output" aria-live="off">
            {live.preview.answer || '…'}
          </pre>
        </section>
      )}

      <section className="card" aria-label="Completed requests">
        <h2>Results so far</h2>
        {rows.length === 0 ? (
          <p className="muted">No results yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Case</th>
                  <th>Outcome</th>
                  <th className="num">Latency</th>
                  <th className="num">Tokens/s</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const c = cases.get(row.caseId);
                  return (
                    <tr key={row.id}>
                      <td>
                        <ModelChip
                          name={row.model}
                          source={modelInfo.get(row.model)?.source}
                          provider={modelInfo.get(row.model)?.provider}
                          providerKind={modelInfo.get(row.model)?.provider_kind}
                        />
                      </td>
                      <td>
                        {c?.title || c?.prompt.slice(0, 60) || `case ${row.caseId}`}
                        {row.repeat > 0 && <span className="muted"> #{row.repeat + 1}</span>}
                      </td>
                      <td>
                        <OutcomeBadge outcome={row.outcome} value={row.value} />
                        {row.cold && (
                          <span className="badge warn" style={{ marginLeft: 4 }}>
                            cold
                          </span>
                        )}
                      </td>
                      <td className="num">{fmtMs(row.latency)}</td>
                      <td className="num">{fmtNum(row.tps)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
