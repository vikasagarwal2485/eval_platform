import { useState } from 'react';
import { useAgentCatalog, usePlaygroundMutations, useSkills } from '../../api/hooks';
import type { Agent, PlaygroundSpawnResult } from '../../api/types';
import { Banner, Empty, ErrorBox, Spinner } from '../ui';
import AgentTurnsPanel from './AgentTurnsPanel';

/** Lets the user enable an agent for the Playground (picking its matching catalog flavor), then
 * spawn it with a system prompt, attached skills and a one-shot task - the real catalog script,
 * launched from the browser, with its spawn credentials automatically supplied (spec
 * `agent-playground`). */
export default function PlaygroundPanel({ agent }: { agent: Agent }) {
  const { data: catalog, isLoading: catalogLoading, error: catalogError } = useAgentCatalog();
  const { data: skills } = useSkills();
  const { enable, disable, rotate, spawn } = usePlaygroundMutations(agent.id);

  const [selectedFlavor, setSelectedFlavor] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [task, setTask] = useState('');
  const [shownToken, setShownToken] = useState<string | null>(null);
  const [spawnResult, setSpawnResult] = useState<PlaygroundSpawnResult | null>(null);

  if (catalogLoading) return <Spinner label="Loading agent catalog" />;
  if (catalogError) return <ErrorBox error={catalogError} title="Could not load the agent catalog." />;

  const matchingFlavors = (catalog ?? []).filter((f) => f.kind === agent.kind);

  if (!agent.playground_eligible) {
    return (
      <div className="stack">
        {matchingFlavors.length === 0 ? (
          <Empty title="No matching catalog flavor">
            <p>
              No catalog flavor matches this agent&apos;s kind (&quot;{agent.kind}&quot;), so it
              can&apos;t be spawned from the Playground yet.
            </p>
          </Empty>
        ) : (
          <section className="card">
            <h2>Enable the Playground for this agent</h2>
            <p className="small muted">
              Pick the catalog flavor this agent&apos;s own script matches. The platform will
              capture a usable ingest token and mint a scoped gateway virtual key for it
              automatically - no manual copy-pasting required afterward.
            </p>
            <div className="field">
              <label htmlFor="flavor-select">Flavor</label>
              <select
                id="flavor-select"
                value={selectedFlavor}
                onChange={(e) => setSelectedFlavor(e.target.value)}
              >
                <option value="" disabled>
                  Select a flavor…
                </option>
                {matchingFlavors.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.id} — {f.description}
                  </option>
                ))}
              </select>
            </div>
            {enable.error && <ErrorBox error={enable.error} title="Could not enable the Playground." />}
            <button
              type="button"
              disabled={!selectedFlavor || enable.isPending}
              onClick={() =>
                enable.mutate(selectedFlavor, { onSuccess: (a) => setShownToken(a.token ?? null) })
              }
            >
              {enable.isPending ? 'Enabling…' : 'Enable Playground'}
            </button>
            {shownToken && (
              <Banner kind="info">
                New ingest token (shown once): <code>{shownToken}</code>
              </Banner>
            )}
          </section>
        )}
      </div>
    );
  }

  const needsHandoff = agent.kind === 'router' && agent.handoff_agent_names.length === 0;

  return (
    <div className="grid-2">
      <div className="stack">
        <section className="card">
          <div className="card-head">
            <h2>Spawn</h2>
            <span className="badge">{agent.flavor}</span>
          </div>

          {needsHandoff && (
            <Banner kind="warn">
              This router has no hand-off agents configured yet - set at least one in the Settings
              tab before spawning.
            </Banner>
          )}
          {!agent.playground_gateway_key_configured && agent.kind !== 'chatbot' && (
            <Banner kind="warn">
              No gateway virtual key is stored for this agent yet (minting may have failed when it
              was enabled) - rotate credentials below before spawning.
            </Banner>
          )}

          <div className="field">
            <label htmlFor="pg-system-prompt">System prompt (optional)</label>
            <textarea
              id="pg-system-prompt"
              rows={3}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="Overrides this script's hardcoded default prompt…"
            />
          </div>

          <div className="field">
            <span id="pg-skills-label">Skills (optional)</span>
            <div className="stack" aria-labelledby="pg-skills-label" style={{ gap: 4 }}>
              {(skills ?? []).length === 0 && <p className="small muted">No skills registered yet.</p>}
              {(skills ?? []).map((s) => (
                <label key={s.id} className="check">
                  <input
                    type="checkbox"
                    checked={selectedSkills.includes(s.name)}
                    onChange={(e) =>
                      setSelectedSkills(
                        e.target.checked
                          ? [...selectedSkills, s.name]
                          : selectedSkills.filter((n) => n !== s.name),
                      )
                    }
                  />
                  <span>{s.name}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="field">
            <label htmlFor="pg-task">Task</label>
            <textarea
              id="pg-task"
              rows={4}
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="What should this agent do?"
            />
          </div>

          {spawn.error && <ErrorBox error={spawn.error} title="Spawn failed." />}
          {spawnResult && spawnResult.status !== 'ok' && (
            <Banner kind="warn">
              Spawn {spawnResult.status}
              {spawnResult.stderr ? `: ${spawnResult.stderr}` : ''}
            </Banner>
          )}
          {spawnResult && spawnResult.status === 'ok' && (
            <Banner kind="info">Spawn finished - watch the live conversation on the right.</Banner>
          )}

          <button
            type="button"
            disabled={!task.trim() || spawn.isPending}
            onClick={() => {
              setSpawnResult(null);
              spawn.mutate(
                { system_prompt: systemPrompt.trim() || null, skills: selectedSkills, task: task.trim() },
                { onSuccess: setSpawnResult },
              );
            }}
          >
            {spawn.isPending ? 'Spawning…' : 'Spawn'}
          </button>
        </section>

        <section className="card">
          <h2>Playground credentials</h2>
          <p className="small">
            Gateway key:{' '}
            {agent.playground_gateway_key_configured ? (
              <span className="badge good">configured</span>
            ) : (
              <span className="badge warn">not configured</span>
            )}
          </p>
          <div className="row">
            <button
              type="button"
              onClick={() =>
                rotate.mutate(undefined, { onSuccess: (a) => setShownToken(a.token ?? null) })
              }
              disabled={rotate.isPending}
            >
              {rotate.isPending ? 'Rotating…' : 'Rotate credentials'}
            </button>
            <button
              type="button"
              className="link"
              onClick={() => {
                if (confirm('Disable the Playground for this agent? It can be re-enabled later.'))
                  disable.mutate();
              }}
              disabled={disable.isPending}
            >
              Disable Playground
            </button>
          </div>
          {shownToken && (
            <Banner kind="info">
              New ingest token (shown once): <code>{shownToken}</code>
            </Banner>
          )}
        </section>
      </div>

      <div>
        <h2>Live conversation</h2>
        <AgentTurnsPanel agentId={agent.id} mode="live" />
      </div>
    </div>
  );
}
