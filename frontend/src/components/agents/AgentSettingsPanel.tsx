import { useState } from 'react';
import { ApiError } from '../../api/client';
import { useAgentMutations, useAgents, useModels } from '../../api/hooks';
import type {
  Agent,
  AgentKind,
  DeclaredModels,
  GatewaySyncResult,
  ModelInfo,
  RubricCriterion,
} from '../../api/types';
import DeclaredModelPicker from './DeclaredModelPicker';
import EvaluatorPicker from './EvaluatorPicker';
import { Banner, ErrorBox } from '../ui';
import { DECLARED_MODELS_HINT, TASK_TYPE_OPTIONS } from '../../lib/declaredModelTasks';

/** One declared-model row for editing: a task-type key paired with the model it uses, plus an optional
 * temperature override synced to that task type's gateway model group (`add-gateway-model-sync`) and an
 * optional fallback model synced to its own gateway group (`add-declared-model-fallback`) - same shape the
 * registration form uses, see AgentsPage.tsx's DeclaredModelsFields. */
interface DeclaredModelRow {
  key: string;
  model: string;
  temperature: string; // raw input string; parsed to a number only when building the save payload
  fallback: string; // empty means "no fallback configured" - omitted entirely from the save payload
}

function toRows(declaredModels: DeclaredModels): DeclaredModelRow[] {
  const rows = Object.entries(declaredModels).map(([key, entry]) => {
    if (typeof entry === 'string') return { key, model: entry, temperature: '', fallback: '' };
    const temp = entry.params?.temperature;
    return {
      key,
      model: entry.model,
      temperature: typeof temp === 'number' ? String(temp) : '',
      fallback: entry.fallback ?? '',
    };
  });
  return rows.length ? rows : [{ key: 'default', model: '', temperature: '', fallback: '' }];
}

function rowsToDeclaredModels(rows: DeclaredModelRow[]): DeclaredModels {
  return Object.fromEntries(
    rows
      .filter((r) => r.key.trim() && r.model.trim())
      .map((r) => {
        const temp = r.temperature.trim();
        const fallback = r.fallback.trim();
        if (!temp && !fallback) return [r.key.trim(), r.model.trim()];
        return [
          r.key.trim(),
          {
            model: r.model.trim(),
            ...(temp ? { params: { temperature: Number(temp) } } : {}),
            ...(fallback ? { fallback } : {}),
          },
        ];
      }),
  );
}

function DeclaredModelsEditor({
  rows,
  onChange,
  models,
  loading,
  acknowledgedProviders,
}: {
  rows: DeclaredModelRow[];
  onChange: (rows: DeclaredModelRow[]) => void;
  models: ModelInfo[] | undefined;
  loading: boolean;
  acknowledgedProviders: string[];
}) {
  const update = (i: number, patch: Partial<DeclaredModelRow>) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  return (
    <div className="field">
      <span id="declared-models-label">Declared models</span>
      <p className="small muted" style={{ marginTop: 0 }}>
        {DECLARED_MODELS_HINT}
      </p>
      <div className="stack" aria-labelledby="declared-models-label">
        {rows.map((row, i) => (
          <div className="stack" key={i} style={{ gap: 4 }}>
            <div className="row">
              <select
                aria-label={`Task type for declared model ${i + 1}`}
                value={row.key}
                onChange={(e) => update(i, { key: e.target.value })}
                style={{ maxWidth: 220 }}
              >
                <option value="" disabled>
                  Select a task…
                </option>
                {TASK_TYPE_OPTIONS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
                {row.key && !TASK_TYPE_OPTIONS.some((t) => t.value === row.key) && (
                  <option value={row.key}>{row.key} (custom)</option>
                )}
              </select>
              <DeclaredModelPicker
                ariaLabel={`Model for declared model ${i + 1}`}
                models={models}
                loading={loading}
                value={row.model}
                onChange={(model) => update(i, { model })}
                acknowledgedProviders={acknowledgedProviders}
              />
              <input
                aria-label={`Temperature for declared model ${i + 1}`}
                placeholder="temperature (optional)"
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={row.temperature}
                onChange={(e) => update(i, { temperature: e.target.value })}
                style={{ maxWidth: 160 }}
              />
              <button
                type="button"
                className="link"
                onClick={() => onChange(rows.filter((_, idx) => idx !== i))}
                disabled={rows.length <= 1}
                aria-label={`Remove declared model ${i + 1}`}
              >
                Remove
              </button>
            </div>
            <div className="row" style={{ paddingLeft: 232 }}>
              <span className="muted small">Fallback (optional):</span>
              <DeclaredModelPicker
                ariaLabel={`Fallback model for declared model ${i + 1}`}
                models={models}
                loading={loading}
                value={row.fallback}
                onChange={(fallback) => update(i, { fallback })}
                acknowledgedProviders={acknowledgedProviders}
              />
            </div>
          </div>
        ))}
        <button
          type="button"
          className="link"
          onClick={() => onChange([...rows, { key: '', model: '', temperature: '', fallback: '' }])}
        >
          + Add another model
        </button>
      </div>
      <p className="small muted">
        A model from a hosted provider needs the same data-sharing acknowledgment an evaluator does.
        Otherwise informational - the platform checks, at evaluation time, which models a turn
        actually used.
      </p>
    </div>
  );
}

/** Shows a `gateway_sync` result after a save that touched declared_models - mirrors AgentsPage.tsx's
 * GatewaySyncStatus, silent when sync wasn't attempted or nothing was worth reporting. */
function GatewaySyncStatus({ result }: { result: GatewaySyncResult | undefined }) {
  if (!result) return null;
  const notable = Object.entries(result).filter(([, r]) => r.status !== 'ok');
  if (!notable.length) return null;
  return (
    <div className="small muted" style={{ marginTop: 8 }} role="status">
      {notable.map(([taskType, r]) => (
        <div key={taskType}>
          Gateway sync {r.status}
          {taskType !== '*' ? ` (${taskType})` : ''}
          {r.detail ? `: ${r.detail}` : ''}
        </div>
      ))}
    </div>
  );
}

function RubricEditor({
  rubric,
  onChange,
}: {
  rubric: RubricCriterion[];
  onChange: (r: RubricCriterion[]) => void;
}) {
  return (
    <div>
      {rubric.map((c, i) => (
        <div key={i} className="row" style={{ marginBottom: 6 }}>
          <input
            aria-label={`Criterion ${i + 1} name`}
            placeholder="Name"
            value={c.name}
            onChange={(e) =>
              onChange(rubric.map((r, j) => (j === i ? { ...r, name: e.target.value } : r)))
            }
            style={{ maxWidth: 160 }}
          />
          <input
            aria-label={`Criterion ${i + 1} description`}
            placeholder="Description"
            value={c.description ?? ''}
            onChange={(e) =>
              onChange(rubric.map((r, j) => (j === i ? { ...r, description: e.target.value } : r)))
            }
            style={{ flex: 1 }}
          />
          <button
            type="button"
            className="link"
            onClick={() => onChange(rubric.filter((_, j) => j !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...rubric, { name: '', description: '' }])}>
        Add criterion
      </button>
    </div>
  );
}

export default function AgentSettingsPanel({ agent }: { agent: Agent }) {
  const { data: models, isLoading, error: modelsError } = useModels();
  const { data: allAgents } = useAgents();
  const { update, pause, resume, rotateToken, remove } = useAgentMutations(agent.id);

  const [kind, setKind] = useState<AgentKind>(agent.kind);
  const [declaredModelRows, setDeclaredModelRows] = useState<DeclaredModelRow[]>(
    toRows(agent.declared_models),
  );
  const [handoffAgentNames, setHandoffAgentNames] = useState<string[]>(agent.handoff_agent_names);
  const [evaluators, setEvaluators] = useState(agent.eval_config.evaluators);
  const [sampleRate, setSampleRate] = useState(agent.eval_config.sample_rate);
  const [quietPeriod, setQuietPeriod] = useState(agent.eval_config.quiet_period_s);
  const [contextTurns, setContextTurns] = useState(agent.eval_config.context_turns);
  const [attentionThreshold, setAttentionThreshold] = useState(
    agent.eval_config.attention_threshold,
  );
  const [useCustomRubric, setUseCustomRubric] = useState(!!agent.rubric);
  const [rubric, setRubric] = useState<RubricCriterion[]>(agent.rubric ?? []);
  const [pendingAcks, setPendingAcks] = useState<string[]>([]);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [gatewaySync, setGatewaySync] = useState<GatewaySyncResult | undefined>(undefined);

  const ackNeeded =
    update.error instanceof ApiError && update.error.code === 'ack_required'
      ? ((update.error.detail as { provider?: string } | undefined)?.provider ?? null)
      : null;

  const save = () => {
    update.mutate(
      {
        kind,
        declared_models: rowsToDeclaredModels(declaredModelRows),
        eval_config: {
          evaluators,
          sample_rate: sampleRate,
          quiet_period_s: quietPeriod,
          context_turns: contextTurns,
          attention_threshold: attentionThreshold,
        },
        rubric: useCustomRubric ? rubric.filter((c) => c.name.trim()) : null,
        clear_rubric: !useCustomRubric,
        provider_acks: pendingAcks,
        // Driven by the *edited* kind, not agent.kind: handoff_agent_names is only meaningful for a
        // router, so changing kind away from it must clear the now-invalid list in the same
        // request - [] unambiguously means "cleared" (no separate clear_* flag needed, unlike the
        // single-name field this replaced).
        handoff_agent_names: kind === 'router' ? handoffAgentNames : [],
      },
      { onSuccess: (a) => setGatewaySync(a.gateway_sync) },
    );
  };

  return (
    <div className="stack">
      {ackNeeded && !pendingAcks.includes(ackNeeded) && (
        <Banner kind="warn">
          A declared model or evaluator from <strong>{ackNeeded}</strong> sends this agent&apos;s
          live conversations to it.{' '}
          <button
            type="button"
            className="link"
            onClick={() => setPendingAcks([...pendingAcks, ackNeeded])}
          >
            Acknowledge and save
          </button>
        </Banner>
      )}
      {update.error && !ackNeeded && (
        <ErrorBox error={update.error} title="Could not save settings." />
      )}

      <section className="card">
        <div className="card-head">
          <h2>Agent</h2>
        </div>
        <div className="field">
          <label htmlFor="agent-kind">Kind</label>
          <select
            id="agent-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as AgentKind)}
            style={{ maxWidth: 220 }}
          >
            <option value="chatbot">Chatbot</option>
            <option value="reasoning">Reasoning</option>
            <option value="router">Router</option>
          </select>
          {kind !== agent.kind && (
            <p className="small muted">
              Changing kind also changes the built-in rubric used when no custom rubric is set, and
              is rejected if this agent is playground-eligible under a flavor that no longer
              matches, or is another router&apos;s hand-off target (and the new kind isn&apos;t
              &quot;reasoning&quot;).
            </p>
          )}
        </div>
        <DeclaredModelsEditor
          rows={declaredModelRows}
          onChange={setDeclaredModelRows}
          models={models}
          loading={isLoading}
          acknowledgedProviders={[...agent.provider_acks, ...pendingAcks]}
        />
        {kind === 'router' && (
          <div className="field">
            <span>Hand-off agents</span>
            <p className="small muted" style={{ marginTop: 0 }}>
              One or more separate, independently registered agents this router may hand problems
              off to - any kind (its own registered kind is purely descriptive; nothing in the
              spawn mechanism depends on it). At least one is required for a router-kind agent; the
              platform places no limit on how many, though today&apos;s reference router script
              only ever uses the first.
            </p>
            <div className="stack" role="group" aria-label="Hand-off agents" style={{ gap: 4 }}>
              {(allAgents ?? [])
                .filter((a) => a.id !== agent.id)
                .map((a) => (
                  <label key={a.id} className="check">
                    <input
                      type="checkbox"
                      checked={handoffAgentNames.includes(a.name)}
                      onChange={(e) =>
                        setHandoffAgentNames(
                          e.target.checked
                            ? [...handoffAgentNames, a.name]
                            : handoffAgentNames.filter((n) => n !== a.name),
                        )
                      }
                    />
                    <span>
                      {a.name} <span className="muted small">({a.kind})</span>
                    </span>
                  </label>
                ))}
              {(allAgents ?? []).filter((a) => a.id !== agent.id).length === 0 && (
                <p className="small muted">No other agents are registered yet - register one first.</p>
              )}
            </div>
            {handoffAgentNames.length === 0 && (
              <p className="small field-error">At least one hand-off agent is required.</p>
            )}
          </div>
        )}
        <div className="row">
          <button
            type="button"
            onClick={save}
            disabled={update.isPending || (kind === 'router' && handoffAgentNames.length === 0)}
          >
            {update.isPending ? 'Saving…' : 'Save settings'}
          </button>
        </div>
        <GatewaySyncStatus result={gatewaySync} />
        <div className="row">
          {agent.status === 'active' ? (
            <button type="button" onClick={() => pause.mutate()} disabled={pause.isPending}>
              Pause
            </button>
          ) : (
            <button type="button" onClick={() => resume.mutate()} disabled={resume.isPending}>
              Resume
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              rotateToken.mutate(undefined, {
                onSuccess: (a) => setNewToken(a.token ?? null),
              });
            }}
            disabled={rotateToken.isPending}
          >
            Rotate ingest token
          </button>
          <button
            type="button"
            className="link"
            onClick={() => {
              if (
                confirm(
                  `Delete agent "${agent.name}"? This removes all of its turns and evaluations.`,
                )
              )
                remove.mutate();
            }}
          >
            Delete agent
          </button>
        </div>
        {newToken && (
          <Banner kind="info">
            New ingest token (shown once): <code>{newToken}</code>
          </Banner>
        )}
      </section>

      <section className="card">
        <h2>Evaluation</h2>

        <EvaluatorPicker
          models={models}
          loading={isLoading}
          error={modelsError}
          declaredModels={declaredModelRows.map((r) => r.model).filter(Boolean)}
          selected={evaluators}
          onChange={setEvaluators}
          acknowledgedProviders={[...agent.provider_acks, ...pendingAcks]}
        />

        <div className="grid-2" style={{ marginTop: 12 }}>
          <div className="field">
            <label htmlFor="sample-rate">Sample rate</label>
            <input
              id="sample-rate"
              type="number"
              min={0}
              max={1}
              step={0.1}
              value={sampleRate}
              onChange={(e) => setSampleRate(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="quiet-period">Quiet period (seconds)</label>
            <input
              id="quiet-period"
              type="number"
              min={0}
              value={quietPeriod}
              onChange={(e) => setQuietPeriod(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="context-turns">Context turns</label>
            <input
              id="context-turns"
              type="number"
              min={0}
              value={contextTurns}
              onChange={(e) => setContextTurns(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="attention-threshold">Needs-attention threshold</label>
            <input
              id="attention-threshold"
              type="number"
              min={0}
              max={1}
              step={0.1}
              value={attentionThreshold}
              onChange={(e) => setAttentionThreshold(Number(e.target.value))}
            />
          </div>
        </div>

        <div className="field">
          <label className="check">
            <input
              type="checkbox"
              checked={useCustomRubric}
              onChange={(e) => setUseCustomRubric(e.target.checked)}
            />
            <span>Use a custom rubric (otherwise the built-in rubric for {kind} is used)</span>
          </label>
          {useCustomRubric && <RubricEditor rubric={rubric} onChange={setRubric} />}
        </div>

        <button
          type="button"
          onClick={save}
          disabled={update.isPending || (kind === 'router' && handoffAgentNames.length === 0)}
        >
          {update.isPending ? 'Saving…' : 'Save settings'}
        </button>
      </section>

      <section className="card">
        <h2>Connect this agent</h2>
        <p className="small">
          Ingest token prefix: <code>{agent.token_prefix}…</code> (the full token is shown only
          once, at creation or rotation).
        </p>
        <pre className="output">
          {agent.kind === 'reasoning' &&
            `python -m agents.reasoning_agent --gateway-key <virtual-key> \\\n  --platform-url <this platform's URL> --token <TOKEN> --problem "..."`}
          {agent.kind === 'router' &&
            `python -m agents.classifier_router_agent --gateway-key <virtual-key> \\\n  --reasoning-agent-token <token> --reasoning-agent-gateway-key <key> \\\n  --platform-url <this platform's URL> --token <TOKEN> --problem "..."`}
          {agent.kind === 'chatbot' &&
            (() => {
              const first = Object.values(agent.declared_models)[0];
              const model = first ? (typeof first === 'string' ? first : first.model) : '<model>';
              return `python -m agents.chatbot --model ${model} \\\n  --platform-url <this platform's URL> --token <TOKEN>`;
            })()}
        </pre>
        <p className="small muted">
          Prefer not to run this by hand? Enable this agent for the{' '}
          <strong>Playground</strong> tab above to spawn it from the browser instead.
        </p>
      </section>
    </div>
  );
}
