import { useState } from 'react';
import { useSuiteMutations, useSuites } from '../api/hooks';
import type { CaseIn } from '../api/types';
import { ErrorBox } from './ui';

/** Inline "save this ad-hoc prompt into a suite" control. */
export default function SaveToSuite({ item }: { item: CaseIn }) {
  const { data: suites } = useSuites();
  const { saveAdhoc } = useSuiteMutations();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState('__new__');
  const [name, setName] = useState('');
  const writable = (suites ?? []).filter((s) => !s.is_builtin);

  if (saveAdhoc.isSuccess) return <span className="badge good">saved</span>;
  if (!open)
    return (
      <button type="button" className="link" onClick={() => setOpen(true)}>
        Save to suite…
      </button>
    );
  const save = () =>
    saveAdhoc.mutate(
      target === '__new__'
        ? { case: item, new_suite_name: name.trim() }
        : { case: item, suite_id: Number(target) },
    );
  return (
    <span className="row" style={{ display: 'inline-flex' }}>
      <select aria-label="Target suite" value={target} onChange={(e) => setTarget(e.target.value)}>
        <option value="__new__">New suite…</option>
        {writable.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      {target === '__new__' && (
        <input
          type="text"
          aria-label="New suite name"
          placeholder="Suite name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      )}
      <button
        type="button"
        onClick={save}
        disabled={saveAdhoc.isPending || (target === '__new__' && !name.trim())}
      >
        Save
      </button>
      <button type="button" className="link" onClick={() => setOpen(false)}>
        Cancel
      </button>
      {saveAdhoc.error && <ErrorBox error={saveAdhoc.error} />}
    </span>
  );
}
