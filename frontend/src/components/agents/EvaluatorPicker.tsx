import type { ModelInfo } from '../../api/types';
import { groupModels } from '../ModelPicker';
import { Empty, ErrorBox, Spinner } from '../ui';

interface Props {
  models: ModelInfo[] | undefined;
  loading: boolean;
  error: unknown;
  declaredModel: string;
  selected: string[];
  onChange: (names: string[]) => void;
  /** provider names the current settings form has acknowledged in this session, in addition to `provider_acks` */
  acknowledgedProviders: string[];
}

/** Same local/cloud grouping as the benchmark-run model picker (spec `agent-registry`: an evaluator equal to the
 * agent's declared model is never selectable, and a hosted evaluator needs its provider acknowledged first). */
export default function EvaluatorPicker({
  models,
  loading,
  error,
  declaredModel,
  selected,
  onChange,
  acknowledgedProviders,
}: Props) {
  const toggle = (name: string) =>
    onChange(selected.includes(name) ? selected.filter((n) => n !== name) : [...selected, name]);

  if (loading) return <Spinner label="Loading models" />;
  if (error) return <ErrorBox error={error} title="Could not load models." />;
  if (!models || models.length === 0) return <Empty title="No models available to evaluate with" />;

  return (
    <div className="stack" role="group" aria-label="Evaluators">
      {groupModels(models).map((g) => (
        <fieldset key={g.key} style={{ margin: 0 }}>
          <legend>{g.title}</legend>
          <div className="model-list">
            {g.models.map((m) => {
              const isSelf = m.name === declaredModel;
              const needsAck =
                m.source === 'cloud' && !!m.provider && !acknowledgedProviders.includes(m.provider);
              const disabled = isSelf || !m.available;
              const on = selected.includes(m.name);
              const reasonId = `evaluator-reason-${m.name}`;
              return (
                <div key={m.name} className={`model-card${on ? ' selected' : ''}`}>
                  <label className="check">
                    <input
                      type="checkbox"
                      aria-label={m.name}
                      aria-describedby={disabled || needsAck ? reasonId : undefined}
                      checked={on}
                      disabled={disabled}
                      onChange={() => toggle(m.name)}
                    />
                    <span>{m.source === 'cloud' ? (m.display_name ?? m.name) : m.name}</span>
                  </label>
                  <div className="small muted">
                    <code>{m.name}</code>
                  </div>
                  <div className="row" style={{ marginTop: 6 }}>
                    {m.source === 'cloud' && <span className="badge info">cloud</span>}
                    {isSelf && <span className="badge warn">this agent&apos;s own model</span>}
                    {!m.available && !isSelf && <span className="badge warn">unavailable</span>}
                    {needsAck && !isSelf && (
                      <span className="badge warn">needs acknowledgment</span>
                    )}
                  </div>
                  {isSelf && (
                    <div id={reasonId} className="small muted" style={{ marginTop: 4 }}>
                      An agent cannot evaluate its own declared model.
                    </div>
                  )}
                  {!isSelf && !m.available && (
                    <div id={reasonId} className="small muted" style={{ marginTop: 4 }}>
                      {m.unavailable_reason}
                    </div>
                  )}
                  {!isSelf && needsAck && m.available && (
                    <div id={reasonId} className="small muted" style={{ marginTop: 4 }}>
                      Acknowledge data sharing with {m.provider} below before adding it as an
                      evaluator.
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </fieldset>
      ))}
    </div>
  );
}
