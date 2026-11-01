import { useState } from 'react';
import { useSkillMutations, useSkillsPage } from '../api/hooks';
import type { Skill } from '../api/types';
import { useConfirm } from '../components/ConfirmDialog';
import Pagination, { usePagination } from '../components/Pagination';
import { Empty, ErrorBox, Spinner } from '../components/ui';

function UploadPanel({ onDone }: { onDone: (id: number) => void }) {
  const { importSkill } = useSkillMutations();
  const [fileName, setFileName] = useState('');

  const submit = (content: string, filename: string, contentType: string) =>
    importSkill.mutate(
      { content, filename, content_type: contentType },
      {
        onSuccess: (s) => {
          setFileName('');
          onDone(s.id);
        },
      },
    );

  return (
    <section className="card" aria-labelledby="skill-upload-h">
      <h2 id="skill-upload-h">Upload a skill</h2>
      <p className="muted small">
        Pick a Markdown file from your computer. Its first block becomes the name, the next becomes
        the description, and the rest becomes the instructions.
      </p>
      <div className="field">
        <label htmlFor="skill-upload-file">File (.md)</label>
        <input
          id="skill-upload-file"
          type="file"
          accept=".md,text/markdown"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            setFileName(f.name);
            submit(await f.text(), f.name, f.type || 'text/markdown');
          }}
        />
      </div>
      {fileName && <p className="small muted">Selected: {fileName}</p>}
      {importSkill.error && (
        <div className="mt-md">
          <ErrorBox error={importSkill.error} title="Upload failed; nothing was created." />
        </div>
      )}
    </section>
  );
}

function SkillForm({
  initial,
  busy,
  onSubmit,
  onCancel,
}: {
  initial?: Skill;
  busy: boolean;
  onSubmit: (b: { name: string; description: string; instructions: string }) => void;
  onCancel?: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [instructions, setInstructions] = useState(initial?.instructions ?? '');

  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ name: name.trim(), description, instructions });
      }}
    >
      <div className="field">
        <label htmlFor="skill-name">Name</label>
        <input id="skill-name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="skill-desc">
          Description <span className="hint">(optional)</span>
        </label>
        <input
          id="skill-desc"
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="skill-instructions">Instructions (Markdown)</label>
        <textarea
          id="skill-instructions"
          rows={10}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
        <span className="small muted">
          {instructions.length.toLocaleString()} characters · roughly{' '}
          {Math.ceil(instructions.length / 4).toLocaleString()} tokens of every prompt this skill is
          attached to.
        </span>
      </div>
      <div className="row">
        <button
          type="submit"
          className="primary"
          disabled={!name.trim() || !instructions.trim() || busy}
        >
          {initial ? 'Save' : 'Create skill'}
        </button>
        {onCancel && (
          <button type="button" className="link" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

function SkillDetailView({ skill, onDeleted }: { skill: Skill; onDeleted: () => void }) {
  const m = useSkillMutations();
  const confirm = useConfirm();
  const [editing, setEditing] = useState(false);
  const err = m.update.error ?? m.remove.error;

  if (editing) {
    return (
      <section className="card" aria-label={`Edit skill ${skill.name}`}>
        <h2>Edit skill</h2>
        {!!err && <ErrorBox error={err} />}
        <SkillForm
          key={skill.id}
          initial={skill}
          busy={m.update.isPending}
          onCancel={() => setEditing(false)}
          onSubmit={(b) =>
            m.update.mutate({ id: skill.id, ...b }, { onSuccess: () => setEditing(false) })
          }
        />
      </section>
    );
  }

  return (
    <section className="card" aria-label={`Skill ${skill.name}`}>
      <div className="card-head">
        <h2>{skill.name}</h2>
        <span className="spacer" />
        <button onClick={() => setEditing(true)}>Edit</button>
        <button
          className="danger"
          aria-label={`Delete skill ${skill.name}`}
          onClick={async () => {
            if (
              await confirm({
                title: `Delete skill “${skill.name}”?`,
                body: 'Past runs keep the exact instructions they used.',
                confirmLabel: 'Delete',
                danger: true,
              })
            )
              m.remove.mutate(skill.id, { onSuccess: onDeleted });
          }}
        >
          Delete
        </button>
      </div>
      {!!err && <ErrorBox error={err} />}
      {skill.description && <p className="muted">{skill.description}</p>}
      <pre className="card pre-wrap">{skill.instructions}</pre>
    </section>
  );
}

export default function SkillsPage() {
  const { page, pageSize, setPage, setPageSize, offset, limit } = usePagination();
  const { data, isLoading, error } = useSkillsPage({ limit, offset });
  const skills = data?.items;
  const { create } = useSkillMutations();
  const [selected, setSelected] = useState<number | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const current = selected ?? skills?.[0]?.id ?? null;
  const currentSkill = skills?.find((s) => s.id === current);

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>Skills</h1>
          <p className="muted">
            Named Markdown instructions a run can attach to every model it evaluates, to measure how
            equipping a model with guidance changes its quality, latency and tokens/sec.
          </p>
        </div>
        <button onClick={() => setShowUpload((v) => !v)} aria-expanded={showUpload}>
          Upload…
        </button>
      </div>
      {showUpload && (
        <UploadPanel
          onDone={(id) => {
            setSelected(id);
            setShowUpload(false);
          }}
        />
      )}

      {isLoading && <Spinner label="Loading skills" />}
      {!!error && <ErrorBox error={error} title="Could not load skills." />}
      {skills && (
        <div className={`master-detail ${showUpload ? 'mt-md' : ''}`}>
          <section aria-label="Skill list" className="stack">
            <ul className="stack list-reset">
              {skills.map((s) => (
                <li key={s.id}>
                  <button
                    className={`list-item-btn ${s.id === current ? 'primary' : ''}`}
                    aria-current={s.id === current ? 'true' : undefined}
                    onClick={() => {
                      setSelected(s.id);
                      setShowNew(false);
                    }}
                  >
                    <strong>{s.name}</strong>
                    {s.description && <div className="small muted">{s.description}</div>}
                  </button>
                </li>
              ))}
            </ul>
            <Pagination
              page={page}
              pageSize={pageSize}
              total={data?.total ?? 0}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
            />
            {!showNew ? (
              <button className="primary" onClick={() => setShowNew(true)}>
                New skill
              </button>
            ) : (
              <div className="card">
                <h3>New skill</h3>
                {create.error && <ErrorBox error={create.error} />}
                <SkillForm
                  busy={create.isPending}
                  onCancel={() => setShowNew(false)}
                  onSubmit={(b) =>
                    create.mutate(b, {
                      onSuccess: (s) => {
                        setSelected(s.id);
                        setShowNew(false);
                      },
                    })
                  }
                />
              </div>
            )}
          </section>
          {showNew ? (
            <Empty title="Creating a new skill">Fill in the form on the left.</Empty>
          ) : currentSkill ? (
            <SkillDetailView
              key={currentSkill.id}
              skill={currentSkill}
              onDeleted={() => setSelected(null)}
            />
          ) : (
            <Empty title="No skills yet">Create or upload one on the left.</Empty>
          )}
        </div>
      )}
    </>
  );
}
