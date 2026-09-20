import type { ModelInfo } from '../api/types';
import { fmtBytes } from '../lib/format';
import { Empty, ErrorBox, Spinner } from './ui';

interface Props {
  models: ModelInfo[] | undefined;
  loading: boolean;
  error: unknown;
  selected: string[];
  onChange: (names: string[]) => void;
  onRefresh: () => void;
  refreshing?: boolean;
}

export default function ModelPicker({
  models,
  loading,
  error,
  selected,
  onChange,
  onRefresh,
  refreshing,
}: Props) {
  const toggle = (name: string) =>
    onChange(selected.includes(name) ? selected.filter((n) => n !== name) : [...selected, name]);

  return (
    <section className="card" aria-labelledby="models-h">
      <div className="card-head">
        <h2 id="models-h">1. Models</h2>
        <span className="badge" aria-live="polite">
          {selected.length} selected
        </span>
        <span className="spacer" />
        {models && models.length > 1 && (
          <>
            <button
              type="button"
              className="link"
              onClick={() => onChange(models.map((m) => m.name))}
            >
              Select all
            </button>
            <button
              type="button"
              className="link"
              onClick={() => onChange([])}
              disabled={!selected.length}
            >
              Clear
            </button>
          </>
        )}
        <button type="button" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {loading && <Spinner label="Loading models" />}
      {!!error && <ErrorBox error={error} title="Could not load models." />}
      {models && models.length === 0 && (
        <Empty title="No models installed">
          <p>
            Pull one with <code>ollama pull &lt;model&gt;</code>, then press Refresh.
          </p>
        </Empty>
      )}
      {models && models.length > 0 && (
        <div className="model-list" role="group" aria-label="Installed models">
          {models.map((m) => {
            const on = selected.includes(m.name);
            return (
              <div key={m.name} className={`model-card${on ? ' selected' : ''}`}>
                <label className="check">
                  <input type="checkbox" checked={on} onChange={() => toggle(m.name)} />
                  <span>{m.name}</span>
                </label>
                <div className="small muted">
                  {[m.parameter_size, m.quantization, m.family, fmtBytes(m.size_bytes)]
                    .filter(Boolean)
                    .join(' · ')}
                </div>
                <div className="row" style={{ marginTop: 6 }}>
                  {m.thinking && <span className="badge info">thinking</span>}
                  {m.capabilities
                    .filter((c) => c !== 'thinking' && c !== 'completion')
                    .map((c) => (
                      <span key={c} className="badge">
                        {c}
                      </span>
                    ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
