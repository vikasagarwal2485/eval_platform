import { useState } from 'react';
import { ApiError } from '../../api/client';
import { useAgentMutations, useModels } from '../../api/hooks';
import type { Agent, RubricCriterion } from '../../api/types';
import EvaluatorPicker from './EvaluatorPicker';
import { Banner, ErrorBox } from '../ui';

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
  const { update, pause, resume, rotateToken, remove } = useAgentMutations(agent.id);

  const [declaredModel, setDeclaredModel] = useState(agent.declared_model);
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

  const ackNeeded =
    update.error instanceof ApiError && update.error.code === 'ack_required'
      ? ((update.error.detail as { provider?: string } | undefined)?.provider ?? null)
      : null;

  const save = () => {
    update.mutate({
      declared_model: declaredModel,
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
    });
  };

  return (
    <div className="stack">
      <section className="card">
        <div className="card-head">
          <h2>Agent</h2>
          <span className="badge">{agent.kind}</span>
        </div>
        <div className="field">
          <label htmlFor="declared-model">Declared model</label>
          <input
            id="declared-model"
            value={declaredModel}
            onChange={(e) => setDeclaredModel(e.target.value)}
          />
          <p className="small muted">
            Informational - the platform checks, at evaluation time, which models a turn actually
            used.
          </p>
        </div>
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
        {ackNeeded && !pendingAcks.includes(ackNeeded) && (
          <Banner kind="warn">
            Evaluating with <strong>{ackNeeded}</strong> sends this agent&apos;s live conversations
            to it.{' '}
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

        <EvaluatorPicker
          models={models}
          loading={isLoading}
          error={modelsError}
          declaredModel={declaredModel}
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
            <span>
              Use a custom rubric (otherwise the built-in rubric for {agent.kind} is used)
            </span>
          </label>
          {useCustomRubric && <RubricEditor rubric={rubric} onChange={setRubric} />}
        </div>

        <button type="button" onClick={save} disabled={update.isPending}>
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
          {`python -m agents.chatbot --model ${agent.declared_model} \\\n  --platform-url <this platform's URL> --token <TOKEN>`}
        </pre>
      </section>
    </div>
  );
}
