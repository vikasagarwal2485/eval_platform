import { useMemo, useState } from 'react';
import type { JudgeMode, LeaderRow } from '../api/types';
import { dash, fmtBytes, fmtMs, fmtNum, fmtPct } from '../lib/format';

type Row = LeaderRow & { composite: number | null; judgeMode?: JudgeMode };

interface Col {
  key: string;
  label: string;
  numeric?: boolean;
  /** true when a higher value is better (used only to pick the default sort direction) */
  higherIsBetter?: boolean;
  value: (r: Row) => number | string | null;
  render: (r: Row) => React.ReactNode;
}

const catCell = (cat: 'classification' | 'reasoning' | 'generation') => (r: Row) => {
  const c = r.categories[cat];
  if (!c) return dash;
  if (c.score === null)
    return (
      <span className="muted" title="No scored cases in this category">
        unscored
      </span>
    );
  return (
    <>
      {fmtPct(c.score)}{' '}
      <span className="small muted">
        {c.scored}/{c.total}
      </span>
      {(cat === 'generation' && (r.self_judged || r.judgeMode === 'cross_model')) ||
      c.errors > 0 ? (
        <div style={{ marginTop: 2 }}>
          {cat === 'generation' && r.judgeMode === 'cross_model' && (
            <span
              className="badge info"
              title="Judged only by the other evaluated models; no model graded its own answers"
            >
              cross-judged
              {r.judges_per_answer
                ? ` · ${r.judges_per_answer} judge${r.judges_per_answer > 1 ? 's' : ''}`
                : ''}
            </span>
          )}
          {cat === 'generation' && r.self_judged && (
            <span className="badge warn" title="Judged by a model that is also being evaluated">
              self-judged
            </span>
          )}
          {c.errors > 0 && (
            <span className="badge bad" style={{ marginLeft: 4 }}>
              {c.errors} err
            </span>
          )}
        </div>
      ) : null}
    </>
  );
};

export const COLUMNS: Col[] = [
  {
    key: 'model',
    label: 'Model',
    value: (r) => r.model,
    render: (r) => <strong>{r.model}</strong>,
  },
  {
    key: 'composite',
    label: 'Composite',
    numeric: true,
    higherIsBetter: true,
    value: (r) => r.composite,
    render: (r) => (r.composite === null ? dash : <strong>{fmtPct(r.composite, 1)}</strong>),
  },
  {
    key: 'classification',
    label: 'Classification',
    numeric: true,
    higherIsBetter: true,
    value: (r) => r.categories.classification?.score ?? null,
    render: catCell('classification'),
  },
  {
    key: 'reasoning',
    label: 'Reasoning',
    numeric: true,
    higherIsBetter: true,
    value: (r) => r.categories.reasoning?.score ?? null,
    render: catCell('reasoning'),
  },
  {
    key: 'generation',
    label: 'Generation',
    numeric: true,
    higherIsBetter: true,
    value: (r) => r.categories.generation?.score ?? null,
    render: catCell('generation'),
  },
  {
    key: 'latency',
    label: 'Latency (median)',
    numeric: true,
    value: (r) => r.performance.latency_ms.median,
    render: (r) => fmtMs(r.performance.latency_ms.median),
  },
  {
    key: 'ttft',
    label: 'TTFT (median)',
    numeric: true,
    value: (r) => r.performance.ttft_ms.median,
    render: (r) => fmtMs(r.performance.ttft_ms.median),
  },
  {
    key: 'tps',
    label: 'Tokens/s',
    numeric: true,
    higherIsBetter: true,
    value: (r) => r.performance.tokens_per_s.median,
    render: (r) => fmtNum(r.performance.tokens_per_s.median),
  },
  {
    key: 'tokens',
    label: 'Output tokens',
    numeric: true,
    value: (r) => r.performance.output_tokens.median,
    render: (r) => fmtNum(r.performance.output_tokens.median, 0),
  },
  {
    key: 'memory',
    label: 'Memory',
    numeric: true,
    value: (r) => r.memory?.size ?? null,
    render: (r) => fmtBytes(r.memory?.size),
  },
];

export function sortRows(rows: Row[], key: string, dir: 'asc' | 'desc'): Row[] {
  const col = COLUMNS.find((c) => c.key === key) ?? COLUMNS[1];
  const sign = dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = col.value(a);
    const vb = col.value(b);
    if (va === null && vb === null) return 0;
    if (va === null) return 1; // missing values always last
    if (vb === null) return -1;
    return (
      (typeof va === 'string' ? va.localeCompare(vb as string) : (va as number) - (vb as number)) *
      sign
    );
  });
}

export default function Leaderboard({
  rows: baseRows,
  judgeMode,
}: {
  rows: Row[];
  judgeMode?: JudgeMode;
}) {
  const rows = useMemo(() => baseRows.map((r) => ({ ...r, judgeMode })), [baseRows, judgeMode]);
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' }>({
    key: 'composite',
    dir: 'desc',
  });
  const sorted = useMemo(() => sortRows(rows, sort.key, sort.dir), [rows, sort]);
  const ranks = useMemo(() => {
    const byComposite = sortRows(rows, 'composite', 'desc');
    return new Map(byComposite.map((r, i) => [r.model, r.composite === null ? null : i + 1]));
  }, [rows]);

  const onSort = (col: Col) =>
    setSort((s) =>
      s.key === col.key
        ? { key: col.key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { key: col.key, dir: col.numeric ? (col.higherIsBetter ? 'desc' : 'asc') : 'asc' },
    );

  return (
    <div className="table-wrap">
      <table aria-label="Model leaderboard">
        <thead>
          <tr>
            <th className="num">Rank</th>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                className={c.numeric ? 'num' : undefined}
                aria-sort={
                  sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'
                }
              >
                <button type="button" className="sort" onClick={() => onSort(c)}>
                  {c.label}
                  {sort.key === c.key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr
              key={r.model}
              className={ranks.get(r.model) === 1 && rows.length > 1 ? 'best' : undefined}
            >
              <td className="num">{ranks.get(r.model) ?? dash}</td>
              {COLUMNS.map((c) => (
                <td key={c.key} className={c.numeric ? 'num' : undefined}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
