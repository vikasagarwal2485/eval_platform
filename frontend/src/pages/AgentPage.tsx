import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAgent } from '../api/hooks';
import AgentQualityPanel from '../components/agents/AgentQualityPanel';
import AgentSettingsPanel from '../components/agents/AgentSettingsPanel';
import AgentTurnsPanel from '../components/agents/AgentTurnsPanel';
import { ErrorBox, Spinner } from '../components/ui';

const TABS = ['live', 'conversations', 'quality', 'settings'] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = {
  live: 'Live',
  conversations: 'Conversations',
  quality: 'Quality',
  settings: 'Settings',
};

export default function AgentPage() {
  const { id } = useParams();
  const agentId = Number(id);
  const { data: agent, isLoading, error } = useAgent(agentId);
  const [tab, setTab] = useState<Tab>('live');

  if (isLoading) return <Spinner label="Loading agent" />;
  if (error) return <ErrorBox error={error} title="Could not load this agent." />;
  if (!agent) return null;

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>
            {agent.name} <span className="badge">{agent.kind}</span>{' '}
            <span
              className={`badge ${agent.liveness === 'live' ? 'good' : agent.liveness === 'offline' ? 'warn' : ''}`}
            >
              {agent.liveness}
            </span>
          </h1>
          <p className="muted">
            Declared model: <code>{agent.declared_model}</code>
          </p>
        </div>
      </div>

      <div className="tabs" role="tablist" aria-label="Agent views">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            id={`tab-${t}`}
            aria-selected={tab === t}
            aria-controls={`panel-${t}`}
            className={tab === t ? 'active' : ''}
            onClick={() => setTab(t)}
          >
            {TAB_LABEL[t]}
          </button>
        ))}
      </div>

      {TABS.map(
        (t) =>
          tab === t && (
            <div key={t} role="tabpanel" id={`panel-${t}`} aria-labelledby={`tab-${t}`}>
              {t === 'live' && <AgentTurnsPanel agentId={agent.id} mode="live" />}
              {t === 'conversations' && <AgentTurnsPanel agentId={agent.id} mode="conversations" />}
              {t === 'quality' && <AgentQualityPanel agentId={agent.id} />}
              {t === 'settings' && <AgentSettingsPanel agent={agent} />}
            </div>
          ),
      )}
    </>
  );
}
