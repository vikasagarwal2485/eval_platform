import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAgent } from '../api/hooks';
import type { DeclaredModels } from '../api/types';
import AgentQualityPanel from '../components/agents/AgentQualityPanel';
import AgentSettingsPanel from '../components/agents/AgentSettingsPanel';
import AgentTurnsPanel from '../components/agents/AgentTurnsPanel';
import { ErrorBox, Spinner } from '../components/ui';

/** The model reference out of one declared_models entry, whichever shape it is (mirrors the backend's
 * `declared_model_ref` - `app/schemas.py`). */
function declaredModelRef(entry: DeclaredModels[string]): string {
  return typeof entry === 'string' ? entry : entry.model;
}

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
            Declared models:{' '}
            {Object.entries(agent.declared_models)
              .map(([taskType, entry]) => {
                const model = declaredModelRef(entry);
                return taskType === 'default' ? model : `${taskType}: ${model}`;
              })
              .map((label, i) => (
                <code key={i} style={{ marginRight: 8 }}>
                  {label}
                </code>
              ))}
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
