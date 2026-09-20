import { useState } from 'react';
import { useSuite, useSuiteMutations, useSuites } from '../api/hooks';
import type { CaseIn, CaseOut } from '../api/types';
import CaseForm from '../components/CaseForm';
import { CategoryBadge, Empty, ErrorBox, Spinner } from '../components/ui';

function ImportPanel({ onDone }: { onDone: (id: number) => void }) {
  const { importSuite } = useSuiteMutations();
  const [content, setContent] = useState('');
  const [name, setName] = useState('');
  const submit = () =>
    importSuite.mutate(
      { content, name: name.trim() || undefined },
      {
        onSuccess: (s) => {
          setContent('');
          setName('');
          onDone(s.id);
        },
      },
    );
  return (
    <section className="card" aria-labelledby="imp-h">
      <h2 id="imp-h">Import a suite</h2>
      <div className="field">
        <label htmlFor="imp-file">File (JSON or YAML)</label>
        <input
          id="imp-file"
          type="file"
          accept=".json,.yaml,.yml,application/json"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (f) setContent(await f.text());
          }}
        />
      </div>
      <div className="field">
        <label htmlFor="imp-text">…or paste it here</label>
        <textarea id="imp-text" value={content} onChange={(e) => setContent(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="imp-name">
          Rename on import <span className="hint">(optional, e.g. to avoid a name clash)</span>
        </label>
        <input id="imp-name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <button
        className="primary"
        onClick={submit}
        disabled={!content.trim() || importSuite.isPending}
      >
        Import suite
      </button>
      {importSuite.error && (
        <div style={{ marginTop: 12 }}>
          <ErrorBox error={importSuite.error} title="Import failed; nothing was created." />
        </div>
      )}
    </section>
  );
}

function SuiteDetailView({ id, onDeleted }: { id: number; onDeleted: () => void }) {
  const { data: suite, isLoading, error } = useSuite(id);
  const m = useSuiteMutations();
  const [editing, setEditing] = useState<number | 'new' | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState('');

  if (isLoading) return <Spinner label="Loading suite" />;
  if (error || !suite) return <ErrorBox error={error} title="Could not load the suite." />;
  const ro = suite.is_builtin;
  const err =
    m.update.error ??
    m.remove.error ??
    m.duplicate.error ??
    m.addCase.error ??
    m.updateCase.error ??
    m.deleteCase.error;

  const saveCase = (c: CaseIn, existing?: CaseOut) => {
    const done = { onSuccess: () => setEditing(null) };
    if (existing) m.updateCase.mutate({ id: existing.id, c, suiteId: id }, done);
    else m.addCase.mutate({ suiteId: id, c }, done);
  };

  return (
    <section className="card" aria-label={`Suite ${suite.name}`}>
      <div className="card-head">
        {renaming ? (
          <>
            <input
              type="text"
              aria-label="Suite name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <button
              onClick={() => m.update.mutate({ id, name }, { onSuccess: () => setRenaming(false) })}
              disabled={!name.trim()}
            >
              Save name
            </button>
            <button className="link" onClick={() => setRenaming(false)}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <h2>{suite.name}</h2>
            {ro && <span className="badge info">built-in · read-only</span>}
          </>
        )}
        <span className="spacer" />
        {!ro && !renaming && (
          <button
            onClick={() => {
              setName(suite.name);
              setRenaming(true);
            }}
          >
            Rename
          </button>
        )}
        <button onClick={() => m.duplicate.mutate(id)}>Duplicate</button>
        <a className="btn" href={`/api/suites/${id}/export?format=json`} download>
          Export JSON
        </a>
        <a className="btn" href={`/api/suites/${id}/export?format=yaml`} download>
          Export YAML
        </a>
        {!ro && (
          <button
            className="danger"
            aria-label={`Delete suite ${suite.name}`}
            onClick={() => {
              if (
                window.confirm(
                  `Delete suite “${suite.name}”? Past runs keep their own copy of these cases.`,
                )
              )
                m.remove.mutate(id, { onSuccess: onDeleted });
            }}
          >
            Delete
          </button>
        )}
      </div>
      {suite.description && <p className="muted">{suite.description}</p>}
      {ro && (
        <p className="small muted">
          The built-in suite can’t be edited. Duplicate it to customise a copy.
        </p>
      )}
      {!!err && <ErrorBox error={err} />}

      <div className="table-wrap">
        <table aria-label="Cases">
          <thead>
            <tr>
              <th>Category</th>
              <th>Case</th>
              <th>Expected</th>
              <th>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {suite.cases.map((c) => (
              <tr key={c.id}>
                <td>
                  <CategoryBadge category={c.category} />
                </td>
                <td>
                  <strong>{c.title || c.prompt.slice(0, 60)}</strong>
                  <div className="small muted">
                    {c.prompt.slice(0, 140)}
                    {c.prompt.length > 140 ? '…' : ''}
                  </div>
                </td>
                <td>{c.expected ?? <span className="muted">—</span>}</td>
                <td>
                  {!ro && (
                    <>
                      <button
                        className="link"
                        aria-label={`Edit case ${c.title || c.prompt.slice(0, 30)}`}
                        onClick={() => setEditing(c.id)}
                      >
                        Edit
                      </button>{' '}
                      <button
                        className="link"
                        aria-label={`Delete case ${c.title || c.prompt.slice(0, 30)}`}
                        onClick={() => {
                          if (window.confirm('Delete this case?'))
                            m.deleteCase.mutate({ id: c.id, suiteId: id });
                        }}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {suite.cases.length === 0 && (
        <Empty title="This suite has no cases yet">Add one below.</Empty>
      )}

      {!ro && editing === null && (
        <p style={{ marginTop: 12 }}>
          <button className="primary" onClick={() => setEditing('new')}>
            Add case
          </button>
        </p>
      )}
      {!ro && editing !== null && (
        <div className="card" style={{ marginTop: 12 }}>
          <h3>{editing === 'new' ? 'New case' : 'Edit case'}</h3>
          <CaseForm
            key={String(editing)}
            initial={editing === 'new' ? undefined : suite.cases.find((c) => c.id === editing)}
            submitLabel={editing === 'new' ? 'Add case' : 'Save case'}
            busy={m.addCase.isPending || m.updateCase.isPending}
            onCancel={() => setEditing(null)}
            onSubmit={(c) =>
              saveCase(c, editing === 'new' ? undefined : suite.cases.find((x) => x.id === editing))
            }
          />
        </div>
      )}
    </section>
  );
}

export default function SuitesPage() {
  const { data: suites, isLoading, error } = useSuites();
  const { create } = useSuiteMutations();
  const [selected, setSelected] = useState<number | null>(null);
  const [newName, setNewName] = useState('');
  const [showImport, setShowImport] = useState(false);
  const current = selected ?? suites?.[0]?.id ?? null;

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>Suites</h1>
          <p className="muted">Reusable sets of classification, reasoning and generation cases.</p>
        </div>
        <button onClick={() => setShowImport((v) => !v)} aria-expanded={showImport}>
          Import…
        </button>
      </div>
      {showImport && (
        <ImportPanel
          onDone={(id) => {
            setSelected(id);
            setShowImport(false);
          }}
        />
      )}

      {isLoading && <Spinner label="Loading suites" />}
      {!!error && <ErrorBox error={error} title="Could not load suites." />}
      {suites && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(220px, 300px) 1fr',
            gap: 16,
            marginTop: showImport ? 16 : 0,
          }}
        >
          <section aria-label="Suite list" className="stack">
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }} className="stack">
              {suites.map((s) => (
                <li key={s.id}>
                  <button
                    style={{ width: '100%', textAlign: 'left' }}
                    aria-current={s.id === current ? 'true' : undefined}
                    className={s.id === current ? 'primary' : undefined}
                    onClick={() => setSelected(s.id)}
                  >
                    <strong>{s.name}</strong>
                    <div className="small" style={{ opacity: 0.85 }}>
                      {s.case_count} cases{s.is_builtin ? ' · built-in' : ''}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
            <form
              className="card"
              onSubmit={(e) => {
                e.preventDefault();
                create.mutate(
                  { name: newName.trim() },
                  {
                    onSuccess: (s) => {
                      setNewName('');
                      setSelected(s.id);
                    },
                  },
                );
              }}
            >
              <label htmlFor="new-suite">New suite</label>
              <div className="row">
                <input
                  id="new-suite"
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Name"
                />
                <button type="submit" disabled={!newName.trim() || create.isPending}>
                  Create
                </button>
              </div>
              {create.error && <ErrorBox error={create.error} />}
            </form>
          </section>
          {current !== null ? (
            <SuiteDetailView key={current} id={current} onDeleted={() => setSelected(null)} />
          ) : (
            <Empty title="No suites yet">Create one on the left.</Empty>
          )}
        </div>
      )}
    </>
  );
}
