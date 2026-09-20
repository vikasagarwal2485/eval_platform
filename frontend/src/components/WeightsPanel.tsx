import type { Category, Weights } from '../api/types';
import { CATEGORIES } from '../api/types';
import { titleCase } from '../lib/format';
import { EQUAL_WEIGHTS } from '../lib/scores';

interface Props {
  weights: Weights;
  onChange: (w: Weights) => void;
  present: Category[];
}

export default function WeightsPanel({ weights, onChange, present }: Props) {
  const total = CATEGORIES.filter((c) => present.includes(c)).reduce((n, c) => n + weights[c], 0);
  return (
    <fieldset>
      <legend>Composite weights</legend>
      <div className="row">
        {CATEGORIES.map((c) => {
          const missing = !present.includes(c);
          return (
            <div className="field" key={c} style={{ margin: 0 }}>
              <label htmlFor={`w-${c}`}>
                {titleCase(c)}
                {missing && <span className="hint"> (no cases)</span>}
              </label>
              <input
                id={`w-${c}`}
                type="range"
                min={0}
                max={10}
                step={1}
                value={weights[c]}
                disabled={missing}
                aria-valuetext={
                  total > 0 && !missing
                    ? `${weights[c]} (${Math.round((weights[c] / total) * 100)}% of composite)`
                    : String(weights[c])
                }
                onChange={(e) => onChange({ ...weights, [c]: Number(e.target.value) })}
              />
              <output htmlFor={`w-${c}`} className="small muted" style={{ marginLeft: 6 }}>
                {weights[c]}
                {total > 0 && !missing ? ` · ${Math.round((weights[c] / total) * 100)}%` : ''}
              </output>
            </div>
          );
        })}
        <button type="button" onClick={() => onChange(EQUAL_WEIGHTS)}>
          Reset to equal
        </button>
      </div>
      <p className="small muted" style={{ margin: '6px 0 0' }}>
        Composite = weighted mean of the category scores. Changing weights re-ranks instantly; no
        models are re-run.
      </p>
    </fieldset>
  );
}
