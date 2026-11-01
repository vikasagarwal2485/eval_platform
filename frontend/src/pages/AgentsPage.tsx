import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useAgents, useAgentsPage, useCreateAgent, useModels } from '../api/hooks';
import type { Agent, AgentKind, DeclaredModels, GatewaySyncResult, ModelInfo } from '../api/types';
import DeclaredModelPicker from '../components/agents/DeclaredModelPicker';
import Pagination, { usePagination } from '../components/Pagination';
import { Banner, Empty, ErrorBox, Spinner } from '../components/ui';
import { DECLARED_MODELS_HINT, TASK_TYPE_OPTIONS } from '../lib/declaredModelTasks';

function LivenessBadge({ agent }: { agent: Agent }) {
  const kind = agent.liveness === 'live' ? 'good' : agent.liveness === 'offline' ? 'warn' : '';
  return <span className={`badge ${kind}`}>{agent.liveness}</span>;
}

/** The model reference out of one declared_models entry, whichever shape it is (mirrors the backend's
 * `declared_model_ref` - `app/schemas.py`). */
function declaredModelRef(entry: DeclaredModels[string]): string {
  return typeof entry === 'string' ? entry : entry.model;
}

function AgentCard({ agent }: { agent: Agent }) {
  return (
    <Link to={`/agents/${agent.id}`} className="card agent-card">
      <div className="card-head">
        <h2>{agent.name}</h2>
        <span className="badge">{agent.kind}</span>
        <LivenessBadge agent={agent} />
        {agent.playground_eligible && <span className="badge info">playground</span>}
      </div>
      <div className="small muted">
        {Object.entries(agent.declared_models).map(([taskType, entry]) => (
          <div key={taskType}>
            {taskType !== 'default' && <span className="muted">{taskType}: </span>}
            <code>{declaredModelRef(entry)}</code>
          </div>
        ))}
      </div>
    </Link>
  );
}

/** Shows a `gateway_sync` result after a create/update that touched declared_models - one line per task type,
 * silent when sync wasn't attempted at all (no `gateway_sync` field) or every entry succeeded with nothing
 * else to say. */
function GatewaySyncStatus({ result }: { result: GatewaySyncResult | undefined }) {
  if (!result) return null;
  const notable = Object.entries(result).filter(([, r]) => r.status !== 'ok');
  if (!notable.length) return null;
  return (
    <div className="small muted mt-sm" role="status">
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

/** One declared-model row: a task-type key (e.g. "reasoning", "generation", or "default" for an agent with a
 * single undifferentiated task) paired with the model it uses, plus an optional temperature override synced
 * to that task type's gateway model group (`add-gateway-model-sync`) and an optional fallback model
 * (`add-declared-model-fallback`) synced to its own gateway group for the platform to use if the primary
 * becomes unreachable. */
interface DeclaredModelRow {
  key: string;
  model: string;
  temperature: string; // kept as the input's raw string; parsed to a number only on submit
  fallback: string; // empty means "no fallback configured" - omitted entirely from the payload
}

function DeclaredModelsFields({
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
      <p className="small muted mt-0">{DECLARED_MODELS_HINT}</p>
      <div className="stack" aria-labelledby="declared-models-label">
        {rows.map((row, i) => (
          <div className="stack gap-sm" key={i}>
            <div className="row">
              <select
                aria-label={`Task type for declared model ${i + 1}`}
                value={row.key}
                onChange={(e) => update(i, { key: e.target.value })}
                className="declared-model-task-select"
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
                className="declared-model-temperature"
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
            <div className="row declared-model-fallback-row">
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
    </div>
  );
}

/** Builds the `declared_models` payload from form rows - a plain string when neither a generation-parameter
 * override nor a fallback is set (unchanged shape), an object only when at least one of them is
 * (`add-gateway-model-sync`, `add-declared-model-fallback`). A blank fallback field is omitted entirely, never
 * sent as an empty string. */
export function rowsToDeclaredModels(rows: DeclaredModelRow[]): DeclaredModels {
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

const EMPTY_DECLARED_MODEL_ROWS: DeclaredModelRow[] = [
  { key: 'default', model: '', temperature: '', fallback: '' },
];

function CreateAgentForm() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<AgentKind>('chatbot');
  const [declaredModels, setDeclaredModels] =
    useState<DeclaredModelRow[]>(EMPTY_DECLARED_MODEL_ROWS);
  const [handoffAgentNames, setHandoffAgentNames] = useState<string[]>([]);
  const [token, setToken] = useState<string | null>(null);
  const [gatewaySync, setGatewaySync] = useState<GatewaySyncResult | undefined>(undefined);
  const [pendingAcks, setPendingAcks] = useState<string[]>([]);
  const create = useCreateAgent();
  const { data: models, isLoading: modelsLoading } = useModels();
  const { data: allAgents } = useAgents();
  // A hand-off target's own kind is purely descriptive - any kind is a valid hand-off agent.
  const handoffCandidates = allAgents ?? [];

  const ackNeeded =
    create.error instanceof ApiError && create.error.code === 'ack_required'
      ? ((create.error.detail as { provider?: string } | undefined)?.provider ?? null)
      : null;

  const register = () => {
    create.mutate(
      {
        name,
        kind,
        declared_models: rowsToDeclaredModels(declaredModels),
        provider_acks: pendingAcks,
        // Point 1: mandatory for a router-kind registration - a router with none configured could
        // never hand anything off. Meaningless (and left empty) for any other kind.
        handoff_agent_names: kind === 'router' ? handoffAgentNames : [],
      },
      {
        onSuccess: (a) => {
          setToken(a.token ?? null);
          setGatewaySync(a.gateway_sync);
        },
      },
    );
  };

  if (token) {
    return (
      <div className="card">
        <h3>Agent registered</h3>
        <p>Ingest token (shown once - copy it now):</p>
        <pre className="output">{token}</pre>
        <GatewaySyncStatus result={gatewaySync} />
        <button
          type="button"
          onClick={() => {
            setToken(null);
            setGatewaySync(undefined);
            setPendingAcks([]);
            setOpen(false);
            setName('');
            setKind('chatbot');
            setDeclaredModels(EMPTY_DECLARED_MODEL_ROWS);
            setHandoffAgentNames([]);
          }}
        >
          Done
        </button>
      </div>
    );
  }

  if (!open)
    return (
      <button type="button" onClick={() => setOpen(true)}>
        Register agent
      </button>
    );

  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        register();
      }}
    >
      <h3>Register an agent</h3>
      {ackNeeded && !pendingAcks.includes(ackNeeded) && (
        <Banner kind="warn">
          A declared model from <strong>{ackNeeded}</strong> sends this agent&apos;s live
          conversations to it.{' '}
          <button
            type="button"
            className="link"
            onClick={() => setPendingAcks([...pendingAcks, ackNeeded])}
          >
            Acknowledge and register
          </button>
        </Banner>
      )}
      {create.error && !ackNeeded && <ErrorBox error={create.error} />}
      <div className="field">
        <label htmlFor="agent-name">Name</label>
        <input id="agent-name" required value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="agent-kind">Kind</label>
        <select id="agent-kind" value={kind} onChange={(e) => setKind(e.target.value as AgentKind)}>
          <option value="chatbot">Chatbot</option>
          <option value="reasoning">Reasoning</option>
          <option value="router">Router</option>
        </select>
      </div>
      {kind === 'router' && (
        <div className="field">
          <span>Hand-off agents</span>
          <p className="small muted mt-0">
            One or more separate, independently registered agents this router may hand problems off
            to - any kind - at least one is required.
          </p>
          <div className="stack gap-sm" role="group" aria-label="Hand-off agents">
            {handoffCandidates.map((a) => (
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
            {handoffCandidates.length === 0 && (
              <p className="small muted">No other agents are registered yet - register one first.</p>
            )}
          </div>
          {handoffAgentNames.length === 0 && (
            <p className="small field-error">At least one hand-off agent is required.</p>
          )}
        </div>
      )}
      <DeclaredModelsFields
        rows={declaredModels}
        onChange={setDeclaredModels}
        models={models}
        loading={modelsLoading}
        acknowledgedProviders={pendingAcks}
      />
      <div className="row">
        <button
          type="submit"
          disabled={create.isPending || (kind === 'router' && handoffAgentNames.length === 0)}
        >
          {create.isPending ? 'Registering…' : 'Register'}
        </button>
        <button type="button" className="link" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function AgentsPage() {
  const { page, pageSize, setPage, setPageSize, offset, limit } = usePagination();
  const { data, isLoading, error } = useAgentsPage({ limit, offset });
  const agents = data?.items;

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>Agents</h1>
          <p className="muted">
            Agents run outside this platform and stream their interactions in over the agent SDK; a
            different model evaluates each turn than the one that produced it.
          </p>
        </div>
      </div>

      {isLoading && <Spinner label="Loading agents" />}
      {!!error && <ErrorBox error={error} title="Could not load agents." />}

      <section aria-labelledby="agents-list-h">
        <h2 id="agents-list-h" className="sr-only">
          Registered agents
        </h2>

        {agents && agents.length === 0 && (
          <Empty title="No agents connected yet">
            <p>
              Register one, then run it anywhere with its ingest token and this platform&apos;s URL:
            </p>
            <pre className="output">
              {`python -m agents.chatbot --model <your-model> \\\n  --platform-url <this platform's URL> --token <TOKEN>`}
            </pre>
          </Empty>
        )}

        {agents && agents.length > 0 && (
          <>
            <ul className="stack list-reset" aria-label="Agents">
              {agents.map((a) => (
                <li key={a.id}>
                  <AgentCard agent={a} />
                </li>
              ))}
            </ul>
            <Pagination
              page={page}
              pageSize={pageSize}
              total={data?.total ?? 0}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
            />
          </>
        )}
      </section>

      <div className="mt-md">
        <CreateAgentForm />
      </div>
    </>
  );
}
