import { useState } from 'react';
import { useProviderMutations } from '../api/hooks';
import type { ProviderKind } from '../api/types';
import {
  KIND_DEFAULTS,
  KIND_LABEL,
  validateBaseUrl,
  validateEnvName,
  validateName,
} from '../lib/providers';
import { ErrorBox } from './ui';

/** Registers a provider. There is deliberately no field for an API key: only the variable that holds it. */
export default function ProviderForm({ onDone }: { onDone?: () => void }) {
  const { create } = useProviderMutations();
  const [kind, setKind] = useState<ProviderKind>('openai');
  const [name, setName] = useState(KIND_DEFAULTS.openai.name);
  const [env, setEnv] = useState(KIND_DEFAULTS.openai.env);
  const [baseUrl, setBaseUrl] = useState('');
  const [ack, setAck] = useState(false);
  const [touched, setTouched] = useState({ name: false, env: false });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const changeKind = (k: ProviderKind) => {
    setKind(k);
    if (!touched.name) setName(KIND_DEFAULTS[k].name); // suggestions follow the kind until the user edits them
    if (!touched.env) setEnv(KIND_DEFAULTS[k].env);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const found: Record<string, string> = {};
    const n = validateName(name);
    const v = validateEnvName(env);
    const u = validateBaseUrl(baseUrl);
    if (n) found.name = n;
    if (v) found.env = v;
    if (u) found.baseUrl = u;
    if (!ack) found.ack = `Acknowledge that evaluation content is sent to ${KIND_LABEL[kind]}.`;
    setErrors(found);
    if (Object.keys(found).length) return;
    create.mutate(
      {
        kind,
        name,
        key_env: env.trim(),
        base_url: baseUrl.trim() || null,
        acknowledge_data_sharing: true,
      },
      {
        onSuccess: () => {
          setAck(false);
          setBaseUrl('');
          setTouched({ name: false, env: false });
          onDone?.();
        },
      },
    );
  };

  return (
    <form className="card" onSubmit={submit} aria-labelledby="add-provider-h" noValidate>
      <h2 id="add-provider-h">Add a provider</h2>
      <p className="small muted">
        Enter the <strong>name</strong> of the environment variable that holds the key. The
        application reads it when it makes a call and never stores, shows or exports it.
      </p>
      <div className="row" style={{ alignItems: 'flex-start' }}>
        <div className="field">
          <label htmlFor="pv-kind">Provider</label>
          <select
            id="pv-kind"
            value={kind}
            onChange={(e) => changeKind(e.target.value as ProviderKind)}
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="pv-name">
            Name <span className="hint">(used in model references)</span>
          </label>
          <input
            id="pv-name"
            type="text"
            value={name}
            aria-invalid={!!errors.name}
            aria-describedby={errors.name ? 'pv-name-err' : undefined}
            onChange={(e) => {
              setName(e.target.value);
              setTouched((t) => ({ ...t, name: true }));
            }}
          />
          {errors.name && (
            <div id="pv-name-err" className="field-error">
              {errors.name}
            </div>
          )}
        </div>
        <div className="field">
          <label htmlFor="pv-env">API key environment variable</label>
          <input
            id="pv-env"
            type="text"
            value={env}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={!!errors.env}
            aria-describedby={errors.env ? 'pv-env-err' : undefined}
            onChange={(e) => {
              setEnv(e.target.value);
              setTouched((t) => ({ ...t, env: true }));
            }}
          />
          {errors.env && (
            <div id="pv-env-err" className="field-error">
              {errors.env}
            </div>
          )}
        </div>
      </div>
      <div className="field">
        <label htmlFor="pv-url">
          Base URL{' '}
          <span className="hint">(optional: gateways and OpenAI-compatible endpoints)</span>
        </label>
        <input
          id="pv-url"
          type="text"
          style={{ width: '100%' }}
          value={baseUrl}
          placeholder="https://…"
          aria-invalid={!!errors.baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
        />
        {errors.baseUrl && <div className="field-error">{errors.baseUrl}</div>}
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={ack}
          onChange={(e) => setAck(e.target.checked)}
          aria-describedby="pv-ack-help"
        />
        <span>
          I understand that prompts and model outputs used in evaluations (including other
          models&rsquo; answers when this provider is used as a judge) will be sent to{' '}
          {KIND_LABEL[kind]}.
        </span>
      </label>
      <div id="pv-ack-help" className="small muted" style={{ marginLeft: 24 }}>
        Required. It is recorded with the provider.
      </div>
      {errors.ack && (
        <div className="field-error" role="alert">
          {errors.ack}
        </div>
      )}
      {create.error && (
        <div style={{ marginTop: 12 }}>
          <ErrorBox error={create.error} title="Could not register the provider." />
        </div>
      )}
      <p style={{ marginBottom: 0 }}>
        <button className="primary" type="submit" disabled={create.isPending}>
          {create.isPending ? 'Registering…' : 'Register provider'}
        </button>
      </p>
    </form>
  );
}
