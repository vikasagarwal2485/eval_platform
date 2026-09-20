import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ACTIVE_STATUSES, useRunMutations, useRuns } from '../api/hooks';
import ComparePanel from '../components/ComparePanel';
import { Empty, ErrorBox, Spinner, StatusBadge } from '../components/ui';
import { fmtDate, fmtDuration } from '../lib/format';

export default function HistoryPage() {
  const navigate = useNavigate();
  const { data: runs, isLoading, error } = useRuns();
  const { rerun, remove } = useRunMutations();
  const [picked, setPicked] = useState<number[]>([]);
  const [comparing, setComparing] = useState<[number, number] | null>(null);

  const toggle = (id: number) => {
    setComparing(null);
    setPicked((p) =>
      p.includes(id) ? p.filter((x) => x !== id) : p.length >= 2 ? [p[1], id] : [...p, id],
    );
  };

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>History</h1>
          <p className="muted">
            Past evaluation runs. Select two to see what changed between them.
          </p>
        </div>
        <button
          className="primary"
          disabled={picked.length !== 2}
          onClick={() =>
            setComparing([Math.min(...picked), Math.max(...picked)] as [number, number])
          }
        >
          Compare selected ({picked.length}/2)
        </button>
      </div>

      {isLoading && <Spinner label="Loading runs" />}
      {!!error && <ErrorBox error={error} title="Could not load runs." />}
      {(rerun.error || remove.error) && <ErrorBox error={rerun.error ?? remove.error} />}

      {runs && runs.length === 0 && (
        <Empty title="No runs yet">
          <p>
            Your evaluations will show up here. <Link to="/">Set up your first run</Link>.
          </p>
        </Empty>
      )}

      {runs && runs.length > 0 && (
        <div className="card table-wrap">
          <table aria-label="Runs">
            <thead>
              <tr>
                <th>
                  <span className="sr-only">Select</span>
                </th>
                <th>Run</th>
                <th>Status</th>
                <th>Models</th>
                <th className="num">Cases</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Judge</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const active = ACTIVE_STATUSES.includes(r.status);
                return (
                  <tr key={r.id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Select run ${r.id} for comparison`}
                        checked={picked.includes(r.id)}
                        onChange={() => toggle(r.id)}
                      />
                    </td>
                    <td>
                      <Link to={active ? `/runs/${r.id}/live` : `/runs/${r.id}`}>
                        <strong>
                          #{r.id} {r.name}
                        </strong>
                      </Link>
                      {r.parent_run_id && (
                        <div className="small muted">re-run of #{r.parent_run_id}</div>
                      )}
                    </td>
                    <td>
                      <StatusBadge status={r.status} />
                      {active && (
                        <div className="small muted">
                          {r.progress.completed}/{r.progress.total}
                        </div>
                      )}
                    </td>
                    <td>{r.models.map((m) => m.name).join(', ')}</td>
                    <td className="num">{r.case_count}</td>
                    <td>{fmtDate(r.started_at ?? r.created_at)}</td>
                    <td>{fmtDuration(r.started_at, r.finished_at)}</td>
                    <td>{r.judge_model ?? <span className="muted">none</span>}</td>
                    <td>
                      <button
                        className="link"
                        disabled={active || rerun.isPending}
                        onClick={() =>
                          rerun.mutate(r.id, { onSuccess: (n) => navigate(`/runs/${n.id}/live`) })
                        }
                      >
                        Re-run
                      </button>{' '}
                      <button
                        className="link"
                        disabled={active || remove.isPending}
                        onClick={() => {
                          if (
                            window.confirm(`Delete run #${r.id} “${r.name}” and all its results?`)
                          ) {
                            remove.mutate(r.id);
                            setPicked((p) => p.filter((x) => x !== r.id));
                          }
                        }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {comparing && (
        <div style={{ marginTop: 16 }}>
          <ComparePanel a={comparing[0]} b={comparing[1]} />
        </div>
      )}
    </>
  );
}
