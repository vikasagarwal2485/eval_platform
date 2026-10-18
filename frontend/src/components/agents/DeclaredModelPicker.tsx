import { useState } from 'react';
import type { ModelInfo } from '../../api/types';
import { groupModels } from '../ModelPicker';

interface Props {
  models: ModelInfo[] | undefined;
  loading: boolean;
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  /** provider names already acknowledged for this agent (saved + pending in this session) - mirrors
   * EvaluatorPicker's acknowledgedProviders. Registering an agent's own model from a hosted provider needs the
   * same data-sharing acknowledgment an evaluator does (spec `agent-registry`) - this just surfaces that a
   * selection will need it; the actual acknowledge-and-save flow lives in the enclosing form. */
  acknowledgedProviders: string[];
}

const CUSTOM = '__custom__';

/** A declared-model value picker: local and registered enterprise models grouped the same way
 * EvaluatorPicker/ModelPicker already group them, with a manual-entry fallback for a model not yet known to the
 * platform (e.g. an Ollama model not pulled yet). Single-select, for one declared-models row. */
export default function DeclaredModelPicker({
  models,
  loading,
  value,
  onChange,
  ariaLabel,
  acknowledgedProviders,
}: Props) {
  const list = models ?? [];
  const known = list.some((m) => m.name === value);
  // `null` = no explicit user choice yet - fall back to "custom" only when the value genuinely isn't in the
  // list. Deriving this on every render (rather than freezing it once via a plain useState initializer) matters
  // because `models` often still hasn't loaded on first mount: freezing it then would wrongly lock in custom
  // mode forever, even after the list arrives and turns out to contain `value` after all.
  const [forceCustom, setForceCustom] = useState<boolean | null>(null);
  const customMode = forceCustom ?? (!known && !!value);

  const selected = list.find((m) => m.name === value);
  const needsAck =
    !!selected &&
    selected.source === 'cloud' &&
    !!selected.provider &&
    !acknowledgedProviders.includes(selected.provider);

  if (customMode || list.length === 0) {
    return (
      <div className="row" style={{ flex: 1 }}>
        <input
          aria-label={ariaLabel}
          placeholder="e.g. qwen3:8b or @provider/model"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        {list.length > 0 && (
          <button type="button" className="link" onClick={() => setForceCustom(false)}>
            Pick from list
          </button>
        )}
      </div>
    );
  }

  const groups = groupModels(list);
  return (
    <div className="row" style={{ flex: 1, alignItems: 'center' }}>
      <select
        aria-label={ariaLabel}
        value={known ? value : ''}
        disabled={loading}
        onChange={(e) => {
          if (e.target.value === CUSTOM) {
            setForceCustom(true);
            return;
          }
          onChange(e.target.value);
        }}
      >
        <option value="" disabled>
          {loading ? 'Loading models…' : 'Select a model…'}
        </option>
        {groups.map((g) => (
          <optgroup key={g.key} label={g.title}>
            {g.models.map((m) => (
              <option key={m.name} value={m.name} disabled={!m.available}>
                {m.source === 'cloud' ? (m.display_name ?? m.name) : m.name}
                {!m.available ? ' (unavailable)' : ''}
              </option>
            ))}
          </optgroup>
        ))}
        <option value={CUSTOM}>Custom (type manually)…</option>
      </select>
      {needsAck && <span className="badge warn">needs data-sharing acknowledgment</span>}
    </div>
  );
}
