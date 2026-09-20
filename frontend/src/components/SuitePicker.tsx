import { useState } from 'react';
import { useSuite, useSuites } from '../api/hooks';
import type { Suite } from '../api/types';
import { Empty, ErrorBox, Spinner, CategoryBadge } from './ui';

export interface SuiteSelection {
  suiteIds: number[];
  excluded: Record<number, number[]>; // suite id -> deselected case ids
}

function SuiteCases({
  suiteId,
  excluded,
  onToggle,
}: {
  suiteId: number;
  excluded: number[];
  onToggle: (caseId: number) => void;
}) {
  const { data, isLoading } = useSuite(suiteId);
  if (isLoading) return <Spinner label="Loading cases" />;
  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: '8px 0 0' }}>
      {data?.cases.map((c) => (
        <li key={c.id}>
          <label className="check">
            <input
              type="checkbox"
              checked={!excluded.includes(c.id)}
              onChange={() => onToggle(c.id)}
            />
            <span>
              <CategoryBadge category={c.category} /> {c.title || c.prompt.slice(0, 80)}
            </span>
          </label>
        </li>
      ))}
    </ul>
  );
}

export default function SuitePicker({
  value,
  onChange,
}: {
  value: SuiteSelection;
  onChange: (v: SuiteSelection) => void;
}) {
  const { data: suites, isLoading, error } = useSuites();
  const [open, setOpen] = useState<number | null>(null);

  const toggleSuite = (s: Suite) => {
    const on = value.suiteIds.includes(s.id);
    onChange({
      suiteIds: on ? value.suiteIds.filter((i) => i !== s.id) : [...value.suiteIds, s.id],
      excluded: on ? { ...value.excluded, [s.id]: [] } : value.excluded,
    });
    if (!on) setOpen(s.id);
  };
  const toggleCase = (suiteId: number, caseId: number) => {
    const cur = value.excluded[suiteId] ?? [];
    onChange({
      ...value,
      excluded: {
        ...value.excluded,
        [suiteId]: cur.includes(caseId) ? cur.filter((i) => i !== caseId) : [...cur, caseId],
      },
    });
  };

  if (isLoading) return <Spinner label="Loading suites" />;
  if (error) return <ErrorBox error={error} title="Could not load suites." />;
  if (!suites?.length)
    return <Empty title="No test suites yet">Create one on the Suites page.</Empty>;

  return (
    <div className="stack">
      {suites.map((s) => {
        const on = value.suiteIds.includes(s.id);
        const skipped = (value.excluded[s.id] ?? []).length;
        return (
          <div key={s.id} className={`model-card${on ? ' selected' : ''}`}>
            <div className="row">
              <label className="check">
                <input type="checkbox" checked={on} onChange={() => toggleSuite(s)} />
                <span>{s.name}</span>
              </label>
              <span className="small muted">
                {on ? `${s.case_count - skipped} of ${s.case_count}` : s.case_count} cases
                {Object.entries(s.counts_by_category).map(([c, n]) => ` · ${n} ${c}`)}
              </span>
              <span className="spacer" />
              {on && (
                <button
                  type="button"
                  className="link"
                  aria-expanded={open === s.id}
                  onClick={() => setOpen(open === s.id ? null : s.id)}
                >
                  {open === s.id ? 'Hide cases' : 'Choose cases'}
                </button>
              )}
            </div>
            {s.description && <div className="small muted">{s.description}</div>}
            {on && open === s.id && (
              <SuiteCases
                suiteId={s.id}
                excluded={value.excluded[s.id] ?? []}
                onToggle={(cid) => toggleCase(s.id, cid)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
