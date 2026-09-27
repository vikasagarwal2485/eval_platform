import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAgents, useCreateAgent } from '../api/hooks';
import type { Agent, AgentKind } from '../api/types';
import { Empty, ErrorBox, Spinner } from '../components/ui';

function LivenessBadge({ agent }: { agent: Agent }) {
  const kind = agent.liveness === 'live' ? 'good' : agent.liveness === 'offline' ? 'warn' : '';
  return <span className={`badge ${kind}`}>{agent.liveness}</span>;
}

function AgentCard({ agent }: { agent: Agent }) {
  return (
    <Link to={`/agents/${agent.id}`} className="card agent-card">
      <div className="card-head">
        <h2 style={{ margin: 0, fontSize: '1.05rem' }}>{agent.name}</h2>
        <span className="badge">{agent.kind}</span>
        <LivenessBadge agent={agent} />
      </div>
      <div className="small muted">
        <code>{agent.declared_model}</code>
      </div>
    </Link>
  );
}

function CreateAgentForm() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<AgentKind>('chatbot');
  const [declaredModel, setDeclaredModel] = useState('');
  const [token, setToken] = useState<string | null>(null);
  const create = useCreateAgent();

  if (token) {
    return (
      <div className="card">
        <h3>Agent registered</h3>
        <p>Ingest token (shown once - copy it now):</p>
        <pre className="output">{token}</pre>
        <button
          type="button"
          onClick={() => {
            setToken(null);
            setOpen(false);
            setName('');
            setDeclaredModel('');
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
        create.mutate(
          { name, kind, declared_model: declaredModel },
          { onSuccess: (a) => setToken(a.token ?? null) },
        );
      }}
    >
      <h3>Register an agent</h3>
      {create.error && <ErrorBox error={create.error} />}
      <div className="field">
        <label htmlFor="agent-name">Name</label>
        <input id="agent-name" required value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="agent-kind">Kind</label>
        <select id="agent-kind" value={kind} onChange={(e) => setKind(e.target.value as AgentKind)}>
          <option value="chatbot">Chatbot</option>
          <option value="reasoning">Reasoning</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="agent-model">Declared model</label>
        <input
          id="agent-model"
          required
          placeholder="e.g. qwen3:8b"
          value={declaredModel}
          onChange={(e) => setDeclaredModel(e.target.value)}
        />
      </div>
      <div className="row">
        <button type="submit" disabled={create.isPending}>
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
  const { data: agents, isLoading, error } = useAgents();

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
          <ul
            className="stack"
            aria-label="Agents"
            style={{ listStyle: 'none', margin: 0, padding: 0 }}
          >
            {agents.map((a) => (
              <li key={a.id}>
                <AgentCard agent={a} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <div style={{ marginTop: 16 }}>
        <CreateAgentForm />
      </div>
    </>
  );
}
