import { useState } from 'react';
import { useProviderMutations } from '../api/hooks';
import type { AvailableModel, ConnectionTest, Provider } from '../api/types';
import {
  KIND_LABEL,
  STATUS_LABEL,
  validateApiVersion,
  validateBaseUrl,
  validateEnvName,
} from '../lib/providers';
import { fmtDate } from '../lib/format';
import { Banner, ErrorBox } from './ui';

function ReasoningEffortCell({
  providerId,
  modelId,
  modelRef,
  value,
}: {
  providerId: number;
  modelId: number;
  modelRef: string;
  value: string | null;
}) {
  const m = useProviderMutations();
  const [draft, setDraft] = useState(value ?? '');
  const commit = () => {
    const next = draft.trim() || null;
    if (next !== value) m.updateModel.mutate({ providerId, modelId, reasoning_effort: next });
  };
  return (
    <input
      type="text"
      aria-label={`Reasoning effort: ${modelRef}`}
      value={draft}
      placeholder="low"
      style={{ width: 80 }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
    />
  );
}

function ModelsTable({ provider }: { provider: Provider }) {
  const m = useProviderMutations();
  const error = m.updateModel.error ?? m.removeModel.error;
  const isAzure = provider.kind === 'azure-openai';
  if (!provider.models.length) return <p className="muted small">No models registered yet.</p>;
  return (
    <>
      {!!error && <ErrorBox error={error} />}
      <div className="table-wrap">
        <table aria-label={`Models of ${provider.name}`}>
          <thead>
            <tr>
              <th>{isAzure ? 'Deployment' : 'Model'}</th>
              <th>Reasoning model</th>
              <th>Reasoning effort</th>
              <th>Classification model</th>
              <th>Enabled</th>
              <th>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {provider.models.map((mo) => (
              <tr key={mo.id}>
                <td>
                  <strong>{mo.display_name}</strong>
                  <div className="small muted">
                    <code>{mo.ref}</code>
                  </div>
                </td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Reasoning model: ${mo.ref}`}
                    checked={mo.reasoning}
                    onChange={(e) =>
                      m.updateModel.mutate({
                        providerId: provider.id,
                        modelId: mo.id,
                        reasoning: e.target.checked,
                      })
                    }
                  />
                </td>
                <td>
                  {mo.reasoning ? (
                    <ReasoningEffortCell
                      providerId={provider.id}
                      modelId={mo.id}
                      modelRef={mo.ref}
                      value={mo.reasoning_effort}
                    />
                  ) : (
                    <span className="muted small">n/a</span>
                  )}
                </td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Classification model: ${mo.ref}`}
                    checked={mo.classification}
                    onChange={(e) =>
                      m.updateModel.mutate({
                        providerId: provider.id,
                        modelId: mo.id,
                        classification: e.target.checked,
                      })
                    }
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Enabled: ${mo.ref}`}
                    checked={mo.enabled}
                    onChange={(e) =>
                      m.updateModel.mutate({
                        providerId: provider.id,
                        modelId: mo.id,
                        enabled: e.target.checked,
                      })
                    }
                  />
                </td>
                <td>
                  <button
                    className="link"
                    aria-label={`Remove ${mo.ref}`}
                    onClick={() => {
                      if (window.confirm(`Remove ${mo.ref}? Past runs keep their results.`))
                        m.removeModel.mutate({ providerId: provider.id, modelId: mo.id });
                    }}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const MODEL_ID_PLACEHOLDER: Record<string, string> = {
  openai: 'gpt-4o',
  anthropic: 'claude-sonnet-4-20250514',
  'azure-openai': 'my-o3-mini-deployment',
  ollama: 'qwen3:8b',
};

function AddModels({ provider }: { provider: Provider }) {
  const m = useProviderMutations();
  const isAzure = provider.kind === 'azure-openai';
  const [modelId, setModelId] = useState('');
  const [reasoning, setReasoning] = useState(false);
  const [reasoningEffort, setReasoningEffort] = useState('');
  const [classification, setClassification] = useState(false);
  const [available, setAvailable] = useState<AvailableModel[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const add = (e: React.FormEvent) => {
    e.preventDefault();
    if (!modelId.trim()) return;
    m.addModel.mutate(
      {
        providerId: provider.id,
        model_id: modelId.trim(),
        reasoning,
        reasoning_effort: reasoning && reasoningEffort.trim() ? reasoningEffort.trim() : null,
        classification,
      },
      {
        onSuccess: () => {
          setModelId('');
          setReasoning(false);
          setReasoningEffort('');
          setClassification(false);
        },
      },
    );
  };

  const addPicked = async () => {
    setBusy(true);
    try {
      for (const id of picked)
        await m.addModel.mutateAsync({ providerId: provider.id, model_id: id });
      setPicked([]);
      setAvailable(null);
    } catch {
      /* the error is shown through m.addModel.error */
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack" style={{ marginTop: 12 }}>
      <form
        onSubmit={add}
        className="row"
        aria-label={`Add a model to ${provider.name}`}
        style={{ alignItems: 'flex-end' }}
      >
        <div className="field" style={{ margin: 0 }}>
          <label htmlFor={`mid-${provider.id}`}>{isAzure ? 'Deployment name' : 'Model id'}</label>
          <input
            id={`mid-${provider.id}`}
            type="text"
            value={modelId}
            placeholder={MODEL_ID_PLACEHOLDER[provider.kind]}
            onChange={(e) => setModelId(e.target.value)}
          />
        </div>
        <label className="check" style={{ marginBottom: 6 }}>
          <input
            type="checkbox"
            checked={reasoning}
            onChange={(e) => setReasoning(e.target.checked)}
          />
          <span>Reasoning model</span>
        </label>
        {reasoning && (
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor={`mre-${provider.id}`}>
              Reasoning effort <span className="hint">(optional)</span>
            </label>
            <input
              id={`mre-${provider.id}`}
              type="text"
              value={reasoningEffort}
              placeholder="low"
              onChange={(e) => setReasoningEffort(e.target.value)}
            />
          </div>
        )}
        <label className="check" style={{ marginBottom: 6 }}>
          <input
            type="checkbox"
            checked={classification}
            onChange={(e) => setClassification(e.target.checked)}
          />
          <span>Classification model</span>
        </label>
        <button type="submit" disabled={!modelId.trim() || m.addModel.isPending}>
          Add model
        </button>
        {!isAzure && (
          <button
            type="button"
            onClick={() =>
              m.fetchModels.mutate(provider.id, { onSuccess: (r) => setAvailable(r.models) })
            }
            disabled={m.fetchModels.isPending}
          >
            {m.fetchModels.isPending
              ? 'Fetching…'
              : `Fetch models from ${KIND_LABEL[provider.kind]}`}
          </button>
        )}
      </form>
      {isAzure && (
        <p className="small muted">
          Azure OpenAI deployments can&rsquo;t be auto-discovered; add each deployment name above.
        </p>
      )}
      {!!m.addModel.error && <ErrorBox error={m.addModel.error} title="Could not add the model." />}
      {!!m.fetchModels.error && (
        <ErrorBox error={m.fetchModels.error} title="Could not fetch the model list.">
          {' '}
          You can still add a model by typing its id above.
        </ErrorBox>
      )}
      {available && (
        <fieldset>
          <legend>Models offered by {KIND_LABEL[provider.kind]}</legend>
          {available.length === 0 && <p className="muted">The provider returned no models.</p>}
          <div style={{ maxHeight: 240, overflow: 'auto' }}>
            {available.map((a) => (
              <label key={a.id} className="check" style={{ marginBottom: 4 }}>
                <input
                  type="checkbox"
                  disabled={a.already_added}
                  checked={a.already_added || picked.includes(a.id)}
                  onChange={() =>
                    setPicked((p) =>
                      p.includes(a.id) ? p.filter((x) => x !== a.id) : [...p, a.id],
                    )
                  }
                />
                <span>
                  <code>{a.id}</code>
                  {a.already_added && <span className="muted"> (already added)</span>}
                </span>
              </label>
            ))}
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button
              className="primary"
              type="button"
              disabled={!picked.length || busy}
              onClick={addPicked}
            >
              Add selected ({picked.length})
            </button>
            <button type="button" className="link" onClick={() => setAvailable(null)}>
              Close
            </button>
          </div>
        </fieldset>
      )}
    </div>
  );
}

function EditProvider({ provider, onDone }: { provider: Provider; onDone: () => void }) {
  const { update } = useProviderMutations();
  const isAzure = provider.kind === 'azure-openai';
  const isOllama = provider.kind === 'ollama';
  const [env, setEnv] = useState(provider.key_env ?? '');
  const [url, setUrl] = useState(provider.base_url ?? '');
  const [apiVersion, setApiVersion] = useState(provider.api_version ?? '');
  const [err, setErr] = useState<string | null>(null);
  const save = (e: React.FormEvent) => {
    e.preventDefault();
    let problem = isOllama ? validateBaseUrl(url) : validateEnvName(env) ?? validateBaseUrl(url);
    if (!problem && isAzure && !url.trim()) problem = 'Azure OpenAI requires a base URL.';
    if (!problem && isAzure && !apiVersion.trim()) problem = validateApiVersion(apiVersion);
    setErr(problem);
    if (problem) return;
    update.mutate(
      {
        id: provider.id,
        base_url: url.trim(),
        ...(isOllama ? {} : { key_env: env.trim() }),
        ...(isAzure ? { api_version: apiVersion.trim() } : {}),
      },
      { onSuccess: onDone },
    );
  };
  return (
    <form onSubmit={save} className="stack" aria-label={`Edit ${provider.name}`} noValidate>
      <div className="row">
        {!isOllama && (
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor={`ee-${provider.id}`}>API key environment variable</label>
            <input
              id={`ee-${provider.id}`}
              type="text"
              value={env}
              autoComplete="off"
              onChange={(e) => setEnv(e.target.value)}
            />
          </div>
        )}
        <div className="field" style={{ margin: 0, flex: 1 }}>
          <label htmlFor={`eu-${provider.id}`}>{isOllama ? 'Ollama server URL' : 'Base URL'}</label>
          <input
            id={`eu-${provider.id}`}
            type="text"
            style={{ width: '100%' }}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        {isAzure && (
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor={`eav-${provider.id}`}>API version</label>
            <input
              id={`eav-${provider.id}`}
              type="text"
              value={apiVersion}
              onChange={(e) => setApiVersion(e.target.value)}
            />
          </div>
        )}
      </div>
      {err && (
        <div className="field-error" role="alert">
          {err}
        </div>
      )}
      {!!update.error && <ErrorBox error={update.error} />}
      <div className="row">
        <button className="primary" type="submit" disabled={update.isPending}>
          Save
        </button>
        <button type="button" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function ProviderCard({ provider }: { provider: Provider }) {
  const m = useProviderMutations();
  const [result, setResult] = useState<ConnectionTest | null>(null);
  const [editing, setEditing] = useState(false);
  const status = result ? STATUS_LABEL[result.status] : null;
  const isOllama = provider.kind === 'ollama';

  return (
    <section className="card" aria-label={`Provider ${provider.name}`}>
      <div className="card-head">
        <h2>{provider.name}</h2>
        <span className="badge info">{KIND_LABEL[provider.kind]}</span>
        {isOllama && <span className="badge info">no key needed</span>}
        {!provider.key_available && <span className="badge warn">unavailable</span>}
        {!isOllama && provider.key_available && <span className="badge good">key ready</span>}
        <span className="spacer" />
        <button
          onClick={() => m.test.mutate(provider.id, { onSuccess: setResult })}
          disabled={m.test.isPending}
        >
          {m.test.isPending ? 'Testing…' : 'Test connection'}
        </button>
        <button onClick={() => setEditing((v) => !v)} aria-expanded={editing}>
          Edit
        </button>
        <button
          className="danger"
          aria-label={`Remove provider ${provider.name}`}
          onClick={() => {
            if (
              window.confirm(
                `Remove provider “${provider.name}” and its ${provider.models.length} models? Past runs keep their results.`,
              )
            )
              m.remove.mutate(provider.id);
          }}
        >
          Remove
        </button>
      </div>
      <p className="small muted" style={{ marginTop: 0 }}>
        {isOllama ? (
          <>Server URL <code>{provider.base_url || 'http://localhost:11434 (default)'}</code></>
        ) : (
          <>
            Key variable <code>{provider.key_env}</code>
            {provider.base_url && (
              <>
                {' '}
                · base URL <code>{provider.base_url}</code>
              </>
            )}
            {provider.api_version && (
              <>
                {' '}
                · API version <code>{provider.api_version}</code>
              </>
            )}{' '}
            · data sharing acknowledged {fmtDate(provider.data_sharing_acknowledged_at)}
          </>
        )}
        {provider.last_test_at && (
          <>
            {' '}
            · last tested {fmtDate(provider.last_test_at)} ({provider.last_test_status})
          </>
        )}
      </p>
      {!provider.key_available && (
        <Banner kind="warn">
          {provider.unavailable_reason} - this provider&rsquo;s models cannot be used anywhere
          until this is fixed and &ldquo;Test connection&rdquo; succeeds.
        </Banner>
      )}
      {!!m.remove.error && (
        <ErrorBox error={m.remove.error} title="Could not remove the provider." />
      )}
      {!!m.test.error && <ErrorBox error={m.test.error} />}
      {result && status && (
        <div role="status" className="small" style={{ marginBottom: 8 }}>
          Connection: <span className={`badge ${status.kind}`}>{status.text}</span> {result.message}
        </div>
      )}
      {editing && (
        <div style={{ marginBottom: 12 }}>
          <EditProvider provider={provider} onDone={() => setEditing(false)} />
        </div>
      )}
      <ModelsTable provider={provider} />
      <AddModels provider={provider} />
    </section>
  );
}
