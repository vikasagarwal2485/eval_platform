import { Link } from 'react-router-dom';
import type { ModelInfo } from '../api/types';
import { fmtBytes } from '../lib/format';
import { KIND_LABEL } from '../lib/providers';
import { Banner, Empty, ErrorBox, Spinner } from './ui';

interface Props {
  models: ModelInfo[] | undefined;
  loading: boolean;
  error: unknown;
  selected: string[];
  onChange: (names: string[]) => void;
  onRefresh: () => void;
  refreshing?: boolean;
  /** Ollama could not be reached: local models cannot be used, enterprise models still can */
  ollamaDown?: boolean;
  ollamaUrl?: string;
}

interface Group {
  key: string;
  title: string;
  models: ModelInfo[];
}

/** Local models first, then one group per enterprise provider. */
export function groupModels(models: ModelInfo[]): Group[] {
  const local = models.filter((m) => m.source === 'local');
  const groups: Group[] = local.length
    ? [{ key: 'local', title: 'Local (Ollama)', models: local }]
    : [];
  const providers = [
    ...new Set(models.filter((m) => m.source === 'cloud').map((m) => m.provider ?? '?')),
  ].sort();
  for (const p of providers) {
    const ms = models.filter((m) => m.source === 'cloud' && (m.provider ?? '?') === p);
    groups.push({
      key: `p:${p}`,
      title: `${p} (${KIND_LABEL[ms[0].provider_kind ?? ''] ?? 'provider'})`,
      models: ms,
    });
  }
  return groups;
}

export default function ModelPicker({
  models,
  loading,
  error,
  selected,
  onChange,
  onRefresh,
  refreshing,
  ollamaDown,
  ollamaUrl,
}: Props) {
  const toggle = (name: string) =>
    onChange(selected.includes(name) ? selected.filter((n) => n !== name) : [...selected, name]);
  const usable = (models ?? []).filter((m) => m.available);

  return (
    <section className="card" aria-labelledby="models-h">
      <div className="card-head">
        <h2 id="models-h">1. Models</h2>
        <span className="badge" aria-live="polite">
          {selected.length} selected
        </span>
        <span className="spacer" />
        {usable.length > 1 && (
          <>
            <button
              type="button"
              className="link"
              onClick={() => onChange(usable.map((m) => m.name))}
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
        <Empty title="No models available">
          <p>
            Pull a local model with <code>ollama pull &lt;model&gt;</code> and press Refresh, or
            register an enterprise provider on the <Link to="/providers">Providers</Link> page.
          </p>
        </Empty>
      )}
      {ollamaDown && models && models.length > 0 && (
        <Banner kind="warn">
          Ollama is unreachable{ollamaUrl ? ` at ${ollamaUrl}` : ''}, so local models are
          unavailable. Enterprise models can still be used.
        </Banner>
      )}

      {models && models.length > 0 && (
        <div className="stack" role="group" aria-label="Available models">
          {groupModels(models).map((g) => (
            <fieldset key={g.key} style={{ margin: 0 }}>
              <legend>{g.title}</legend>
              <div className="model-list">
                {g.models.map((m) => {
                  const on = selected.includes(m.name);
                  const cloud = m.source === 'cloud';
                  const reasonId = `reason-${m.name}`;
                  return (
                    <div
                      key={m.name}
                      className={`model-card${on ? ' selected' : ''}`}
                      style={m.available ? undefined : { opacity: 0.75 }}
                    >
                      <label className="check">
                        <input
                          type="checkbox"
                          aria-label={m.name}
                          aria-describedby={m.available ? undefined : reasonId}
                          checked={on}
                          disabled={!m.available}
                          onChange={() => toggle(m.name)}
                        />
                        <span>{cloud ? (m.display_name ?? m.name) : m.name}</span>
                      </label>
                      {cloud ? (
                        <div className="small muted">
                          <code>{m.name}</code>
                        </div>
                      ) : (
                        <div className="small muted">
                          {[m.parameter_size, m.quantization, m.family, fmtBytes(m.size_bytes)]
                            .filter(Boolean)
                            .join(' · ')}
                        </div>
                      )}
                      <div className="row" style={{ marginTop: 6 }}>
                        {cloud && <span className="badge info">cloud</span>}
                        {cloud && m.provider_kind && (
                          <span className="badge">{KIND_LABEL[m.provider_kind]}</span>
                        )}
                        {(m.thinking || m.reasoning) && (
                          <span className="badge info">{cloud ? 'reasoning' : 'thinking'}</span>
                        )}
                        {!cloud &&
                          m.capabilities
                            .filter((c) => c !== 'thinking' && c !== 'completion')
                            .map((c) => (
                              <span key={c} className="badge">
                                {c}
                              </span>
                            ))}
                        {!m.available && <span className="badge warn">unavailable</span>}
                      </div>
                      {!m.available && (
                        <div id={reasonId} className="small muted" style={{ marginTop: 4 }}>
                          {m.unavailable_reason}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </fieldset>
          ))}
        </div>
      )}
    </section>
  );
}
