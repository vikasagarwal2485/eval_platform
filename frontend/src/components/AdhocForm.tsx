import { useState } from 'react';
import type { CaseIn, Category } from '../api/types';
import { CATEGORIES } from '../api/types';

const normalize = (s: string) =>
  s
    .trim()
    .toLowerCase()
    .replace(/[_\-\s]+/g, ' ');

/** Client-side mirror of the server's case validation, so users get errors before submitting. */
export function validateCase(c: CaseIn): string | null {
  if (!c.prompt.trim()) return 'Enter a prompt.';
  if (c.category === 'classification') {
    const labels = (c.labels ?? []).filter(Boolean);
    if (labels.length < 2) return 'Classification needs at least two comma-separated labels.';
    if (new Set(labels.map(normalize)).size !== labels.length) return 'Labels must be unique.';
    if (c.expected && !labels.some((l) => normalize(l) === normalize(c.expected!)))
      return 'The expected label must be one of the labels.';
  }
  if (
    c.category === 'reasoning' &&
    c.comparison === 'numeric' &&
    c.expected &&
    Number.isNaN(Number(c.expected.replace(/,/g, '')))
  )
    return 'A numeric comparison needs a numeric expected answer.';
  return null;
}

export default function AdhocForm({ onAdd }: { onAdd: (c: CaseIn) => void }) {
  const [category, setCategory] = useState<Category>('classification');
  const [prompt, setPrompt] = useState('');
  const [system, setSystem] = useState('');
  const [expected, setExpected] = useState('');
  const [labels, setLabels] = useState('');
  const [comparison, setComparison] = useState<'text' | 'numeric'>('numeric');
  const [tolerance, setTolerance] = useState('0');
  const [maxWords, setMaxWords] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const c: CaseIn = {
      category,
      prompt,
      system_prompt: system.trim() || null,
      expected: expected.trim() || null,
    };
    if (category === 'classification')
      c.labels = labels
        .split(',')
        .map((l) => l.trim())
        .filter(Boolean);
    if (category === 'reasoning') {
      c.comparison = comparison;
      c.tolerance = Number(tolerance) || 0;
    }
    if (category === 'generation' && maxWords) c.constraints = { max_words: Number(maxWords) };
    const problem = validateCase(c);
    setError(problem);
    if (problem) return;
    onAdd(c);
    setPrompt('');
    setExpected('');
  };

  return (
    <form onSubmit={submit} className="stack" aria-label="Ad-hoc prompt">
      <div className="field">
        <label htmlFor="adhoc-cat">Category</label>
        <select
          id="adhoc-cat"
          value={category}
          onChange={(e) => setCategory(e.target.value as Category)}
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="adhoc-prompt">Prompt</label>
        <textarea id="adhoc-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </div>
      {category === 'classification' && (
        <div className="field">
          <label htmlFor="adhoc-labels">
            Labels <span className="hint">(comma-separated, at least two)</span>
          </label>
          <input
            id="adhoc-labels"
            type="text"
            value={labels}
            onChange={(e) => setLabels(e.target.value)}
          />
        </div>
      )}
      {category === 'reasoning' && (
        <div className="row">
          <div className="field">
            <label htmlFor="adhoc-cmp">Compare answers as</label>
            <select
              id="adhoc-cmp"
              value={comparison}
              onChange={(e) => setComparison(e.target.value as 'text' | 'numeric')}
            >
              <option value="numeric">number</option>
              <option value="text">text</option>
            </select>
          </div>
          {comparison === 'numeric' && (
            <div className="field">
              <label htmlFor="adhoc-tol">Tolerance</label>
              <input
                id="adhoc-tol"
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
      {category === 'generation' && (
        <div className="field">
          <label htmlFor="adhoc-max">
            Max words <span className="hint">(optional constraint)</span>
          </label>
          <input
            id="adhoc-max"
            type="number"
            min={1}
            value={maxWords}
            onChange={(e) => setMaxWords(e.target.value)}
          />
        </div>
      )}
      <div className="field">
        <label htmlFor="adhoc-exp">
          Expected answer{' '}
          <span className="hint">
            (optional{category === 'generation' ? ' — not used for generation' : ''})
          </span>
        </label>
        <input
          id="adhoc-exp"
          type="text"
          value={expected}
          onChange={(e) => setExpected(e.target.value)}
        />
      </div>
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
      <div>
        <button type="submit">Add prompt to run</button>
      </div>
    </form>
  );
}
