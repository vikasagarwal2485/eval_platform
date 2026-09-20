import { useState } from 'react';
import type { CaseIn, Category } from '../api/types';
import { CATEGORIES } from '../api/types';
import { validateCase } from './AdhocForm';

const csv = (s: string) =>
  s
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);
const num = (s: string) => (s.trim() === '' ? null : Number(s));

function rubricToText(c?: CaseIn) {
  return (c?.rubric ?? [])
    .map((r) => (r.description ? `${r.name}: ${r.description}` : r.name))
    .join('\n');
}
function textToRubric(t: string) {
  return t
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const i = l.indexOf(':');
      return i > 0
        ? { name: l.slice(0, i).trim(), description: l.slice(i + 1).trim() }
        : { name: l };
    });
}

/** Full test-case editor (used on the Suites page). */
export default function CaseForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
  busy,
}: {
  initial?: CaseIn;
  submitLabel: string;
  onSubmit: (c: CaseIn) => void;
  onCancel?: () => void;
  busy?: boolean;
}) {
  const [category, setCategory] = useState<Category>(initial?.category ?? 'classification');
  const [title, setTitle] = useState(initial?.title ?? '');
  const [prompt, setPrompt] = useState(initial?.prompt ?? '');
  const [system, setSystem] = useState(initial?.system_prompt ?? '');
  const [expected, setExpected] = useState(initial?.expected ?? '');
  const [labels, setLabels] = useState((initial?.labels ?? []).join(', '));
  const [comparison, setComparison] = useState<'text' | 'numeric'>(initial?.comparison ?? 'text');
  const [tolerance, setTolerance] = useState(String(initial?.tolerance ?? 0));
  const [maxWords, setMaxWords] = useState(String(initial?.constraints?.max_words ?? ''));
  const [minWords, setMinWords] = useState(String(initial?.constraints?.min_words ?? ''));
  const [required, setRequired] = useState(
    (initial?.constraints?.required_keywords ?? []).join(', '),
  );
  const [forbidden, setForbidden] = useState(
    (initial?.constraints?.forbidden_keywords ?? []).join(', '),
  );
  const [rubric, setRubric] = useState(rubricToText(initial));
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const c: CaseIn = {
      category,
      title: title.trim(),
      prompt,
      system_prompt: system.trim() || null,
      expected: expected.trim() || null,
    };
    if (category === 'classification') c.labels = csv(labels);
    if (category === 'reasoning') {
      c.comparison = comparison;
      c.tolerance = Number(tolerance) || 0;
    }
    if (category === 'generation') {
      const cons = {
        max_words: num(maxWords),
        min_words: num(minWords),
        required_keywords: csv(required),
        forbidden_keywords: csv(forbidden),
      };
      if (
        cons.max_words ||
        cons.min_words ||
        cons.required_keywords.length ||
        cons.forbidden_keywords.length
      )
        c.constraints = cons;
      const r = textToRubric(rubric);
      if (r.length) c.rubric = r;
    }
    const problem = validateCase(c);
    setError(problem);
    if (!problem) onSubmit(c);
  };

  return (
    <form onSubmit={submit} className="stack" aria-label="Test case">
      <div className="row">
        <div className="field" style={{ margin: 0 }}>
          <label htmlFor="cf-cat">Category</label>
          <select
            id="cf-cat"
            value={category}
            onChange={(e) => setCategory(e.target.value as Category)}
          >
            {CATEGORIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        <div className="field grow" style={{ margin: 0, flex: 1 }}>
          <label htmlFor="cf-title">
            Title <span className="hint">(optional)</span>
          </label>
          <input
            id="cf-title"
            type="text"
            style={{ width: '100%' }}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
      </div>
      <div className="field">
        <label htmlFor="cf-prompt">Prompt</label>
        <textarea id="cf-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </div>
      {category === 'classification' && (
        <div className="field">
          <label htmlFor="cf-labels">
            Allowed labels <span className="hint">(comma-separated, at least two)</span>
          </label>
          <input
            id="cf-labels"
            type="text"
            style={{ width: '100%' }}
            value={labels}
            onChange={(e) => setLabels(e.target.value)}
          />
        </div>
      )}
      {category === 'reasoning' && (
        <div className="row">
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="cf-cmp">Compare answers as</label>
            <select
              id="cf-cmp"
              value={comparison}
              onChange={(e) => setComparison(e.target.value as 'text' | 'numeric')}
            >
              <option value="text">text</option>
              <option value="numeric">number</option>
            </select>
          </div>
          {comparison === 'numeric' && (
            <div className="field" style={{ margin: 0 }}>
              <label htmlFor="cf-tol">
                Tolerance <span className="hint">(absolute)</span>
              </label>
              <input
                id="cf-tol"
                type="number"
                min={0}
                step="any"
                value={tolerance}
                onChange={(e) => setTolerance(e.target.value)}
              />
            </div>
          )}
        </div>
      )}
      <div className="field">
        <label htmlFor="cf-exp">
          Expected answer{' '}
          <span className="hint">
            (optional{category === 'generation' ? '; generation is scored by the judge' : ''})
          </span>
        </label>
        <input
          id="cf-exp"
          type="text"
          style={{ width: '100%' }}
          value={expected}
          onChange={(e) => setExpected(e.target.value)}
        />
      </div>
      {category === 'generation' && (
        <>
          <fieldset>
            <legend>Constraints (checked deterministically)</legend>
            <div className="row">
              <div className="field" style={{ margin: 0 }}>
                <label htmlFor="cf-max">Max words</label>
                <input
                  id="cf-max"
                  type="number"
                  min={1}
                  value={maxWords}
                  onChange={(e) => setMaxWords(e.target.value)}
                />
              </div>
              <div className="field" style={{ margin: 0 }}>
                <label htmlFor="cf-min">Min words</label>
                <input
                  id="cf-min"
                  type="number"
                  min={1}
                  value={minWords}
                  onChange={(e) => setMinWords(e.target.value)}
                />
              </div>
            </div>
            <div className="field" style={{ marginTop: 8 }}>
              <label htmlFor="cf-req">
                Required keywords <span className="hint">(comma-separated)</span>
              </label>
              <input
                id="cf-req"
                type="text"
                style={{ width: '100%' }}
                value={required}
                onChange={(e) => setRequired(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="cf-forb">
                Forbidden keywords <span className="hint">(comma-separated)</span>
              </label>
              <input
                id="cf-forb"
                type="text"
                style={{ width: '100%' }}
                value={forbidden}
                onChange={(e) => setForbidden(e.target.value)}
              />
            </div>
          </fieldset>
          <div className="field">
            <label htmlFor="cf-rubric">
              Judge rubric{' '}
              <span className="hint">
                (one criterion per line, “Name: what good looks like”; scored 1–5)
              </span>
            </label>
            <textarea id="cf-rubric" value={rubric} onChange={(e) => setRubric(e.target.value)} />
          </div>
        </>
      )}
      <details>
        <summary>System prompt (optional)</summary>
        <textarea
          aria-label="System prompt"
          value={system}
          onChange={(e) => setSystem(e.target.value)}
        />
      </details>
      {error && (
        <div className="field-error" role="alert">
          {error}
        </div>
      )}
      <div className="row">
        <button className="primary" type="submit" disabled={busy}>
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
