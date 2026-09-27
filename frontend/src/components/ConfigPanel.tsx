import type { JudgeMode, ModelInfo, RunConfig } from '../api/types';
import { KIND_LABEL } from '../lib/providers';
import NumberField from './NumberField';
import { Banner } from './ui';

interface Props {
  config: RunConfig;
  onChange: (c: RunConfig) => void;
  judgeMode: JudgeMode;
  onJudgeModeChange: (m: JudgeMode) => void;
  judgeModel: string | null;
  onJudgeChange: (m: string | null) => void;
  models: ModelInfo[];
  selectedModels: string[];
  /** cases that would be judged, per model and repeat (used only for the cost estimate) */
  caseCounts: { generation: number; reasoning: number };
  /** every selected case, all categories (used for the generation request estimate) */
  totalCaseCount: number;
  /** shown when the mode was changed automatically */
  notice?: string | null;
  onDismissNotice?: () => void;
}

type ShareReason = 'contestant' | 'single judge' | 'cross-model judge';

/** destination of a request for this model: `local` (Ollama) or the enterprise provider's name */
function destinationOf(m: ModelInfo | undefined, ref: string): string {
  if (m?.source === 'cloud' && m.provider) return m.provider;
  return ref.startsWith('@') ? ref : 'local';
}

function destinationLabel(dest: string, models: ModelInfo[]): string {
  if (dest === 'local') return 'Ollama (local)';
  const kind = models.find((m) => m.provider === dest)?.provider_kind;
  return kind ? `${dest} (${KIND_LABEL[kind]})` : dest;
}

const MODES: { value: JudgeMode; label: string; help: string }[] = [
  { value: 'none', label: 'No judge', help: 'Generation cases stay unscored.' },
  { value: 'single', label: 'Single judge model', help: 'One model scores every answer.' },
  {
    value: 'cross_model',
    label: 'Cross-model judging',
    help: 'Each model’s answers are judged by the other selected models, so no model grades itself.',
  },
];

export default function ConfigPanel({
  config,
  onChange,
  judgeMode,
  onJudgeModeChange,
  judgeModel,
  onJudgeChange,
  models,
  selectedModels,
  caseCounts,
  totalCaseCount,
  notice,
  onDismissNotice,
}: Props) {
  const set = <K extends keyof RunConfig>(k: K, v: RunConfig[K]) => onChange({ ...config, [k]: v });
  const n = selectedModels.length;
  const canCross = n >= 2;
  const selfJudge = judgeMode === 'single' && !!judgeModel && selectedModels.includes(judgeModel);
  const hasGeneration = caseCounts.generation > 0;
  const judgedCases = caseCounts.generation + (config.judge_reasoning ? caseCounts.reasoning : 0);
  const answers = judgedCases * n * config.repeats;
  const judgements = answers * (n - 1);
  const judging = judgeMode !== 'none';
  const availableJudges = models.filter((m) => m.available);

  // ---- data-sharing notice: every provider that will receive prompts or answers, and why
  const reasons = new Map<string, Set<ShareReason>>();
  const addReason = (provider: string | null, reason: ShareReason) => {
    if (!provider) return;
    if (!reasons.has(provider)) reasons.set(provider, new Set());
    reasons.get(provider)!.add(reason);
  };
  for (const ref of selectedModels) {
    const m = models.find((x) => x.name === ref);
    if (m?.source === 'cloud') {
      addReason(m.provider, 'contestant');
      if (judgeMode === 'cross_model') addReason(m.provider, 'cross-model judge');
    }
  }
  if (judgeMode === 'single' && judgeModel) {
    const jm = models.find((x) => x.name === judgeModel);
    if (jm?.source === 'cloud') addReason(jm.provider, 'single judge');
  }

  // ---- request estimate, split by where each request actually goes
  const destCounts = new Map<string, number>();
  const addRequests = (dest: string, count: number) =>
    destCounts.set(dest, (destCounts.get(dest) ?? 0) + count);
  for (const ref of selectedModels) {
    const m = models.find((x) => x.name === ref);
    const dest = destinationOf(m, ref);
    addRequests(dest, totalCaseCount * config.repeats);
    if (judgeMode === 'cross_model' && judgedCases > 0 && n > 1) {
      addRequests(dest, judgedCases * config.repeats * (n - 1)); // this model judges the other n-1
    }
  }
  if (judgeMode === 'single' && judgeModel && judgedCases > 0) {
    const jm = models.find((x) => x.name === judgeModel);
    addRequests(destinationOf(jm, judgeModel), judgedCases * config.repeats * n);
  }
  const showBreakdown = destCounts.size > 0 && (destCounts.size > 1 || reasons.size > 0);

  return (
    <section className="card" aria-labelledby="cfg-h">
      <h2 id="cfg-h">3. Settings</h2>

      <fieldset>
        <legend>Judging (scores generated text)</legend>
        {notice && (
          <Banner kind="info">
            {notice}{' '}
            {onDismissNotice && (
              <button type="button" className="link" onClick={onDismissNotice}>
                Dismiss
              </button>
            )}
          </Banner>
        )}
        <div role="radiogroup" aria-label="Judging mode" className="stack" style={{ gap: 8 }}>
          {MODES.map((m) => {
            const disabled = m.value === 'cross_model' && !canCross;
            const helpId = `judge-mode-${m.value}-help`;
            return (
              <div key={m.value}>
                <label className="check">
                  <input
                    type="radio"
                    name="judge-mode"
                    value={m.value}
                    checked={judgeMode === m.value}
                    disabled={disabled}
                    aria-describedby={helpId}
                    onChange={() => onJudgeModeChange(m.value)}
                  />
                  <span>{m.label}</span>
                </label>
                <div id={helpId} className="small muted" style={{ marginLeft: 24 }}>
                  {m.help}
                  {disabled && ' Needs at least two selected models.'}
                </div>
              </div>
            );
          })}
        </div>

        {judgeMode === 'single' && (
          <div className="field" style={{ marginTop: 12 }}>
            <label htmlFor="judge">Judge model</label>
            <select
              id="judge"
              value={judgeModel ?? ''}
              onChange={(e) => onJudgeChange(e.target.value || null)}
            >
              <option value="">Choose a judge…</option>
              {availableJudges.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.source === 'cloud' ? `${m.display_name ?? m.name} (${m.provider})` : m.name}
                </option>
              ))}
            </select>
            <p className="small muted" style={{ margin: '4px 0 0' }}>
              Any available local or enterprise model can judge, including one that is not being
              evaluated.
            </p>
          </div>
        )}

        {selfJudge && (
          <div style={{ marginTop: 12 }}>
            <Banner kind="warn">
              <strong>{judgeModel}</strong> is both judge and one of the models being evaluated.
              Models tend to favour their own output, so its judged scores will be labelled as
              self-judged.
              {canCross && (
                <div style={{ marginTop: 8 }}>
                  <button
                    type="button"
                    onClick={() => {
                      onJudgeModeChange('cross_model');
                      onJudgeChange(null);
                    }}
                  >
                    Use cross-model judging instead
                  </button>
                </div>
              )}
            </Banner>
          </div>
        )}
        {judgeMode === 'none' && hasGeneration && (
          <div style={{ marginTop: 12 }}>
            <Banner kind="info">
              No judge selected: generation cases will be shown as unscored and excluded from
              composites.
            </Banner>
          </div>
        )}
        {judgeMode === 'cross_model' && (
          <div style={{ marginTop: 12 }}>
            <Banner kind="info">
              Models never grade themselves. Judges can differ in strictness, so scores from
              different judges are informative but not perfectly like-for-like. Each judge’s average
              is shown in the results so you can check.
              {judgedCases > 0 && n >= 2 && (
                <div className="small" style={{ marginTop: 6 }} data-testid="judge-estimate">
                  About {judgements} judgements ({answers} answers × {n - 1} other{' '}
                  {n - 1 === 1 ? 'model' : 'models'}), one judge model at a time after generation.
                </div>
              )}
            </Banner>
          </div>
        )}

        {reasons.size > 0 && (
          <div style={{ marginTop: 12 }}>
            <Banner kind="warn" role="status">
              <strong>This run will send data to:</strong>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {[...reasons.entries()].map(([provider, why]) => (
                  <li key={provider}>
                    {destinationLabel(provider, models)} — as {[...why].join(' and ')}
                  </li>
                ))}
              </ul>
            </Banner>
          </div>
        )}

        {showBreakdown && (
          <div className="small muted" style={{ marginTop: 8 }} data-testid="request-breakdown">
            Estimated requests:{' '}
            {[...destCounts.entries()]
              .map(([dest, count]) => `${destinationLabel(dest, models)}: ${count}`)
              .join(' · ')}
          </div>
        )}

        <label className="check" style={{ marginTop: 12 }}>
          <input
            type="checkbox"
            checked={config.judge_reasoning}
            disabled={!judging}
            onChange={(e) => set('judge_reasoning', e.target.checked)}
          />
          <span>Also judge the quality of reasoning traces</span>
        </label>
      </fieldset>

      <fieldset>
        <legend>Generation</legend>
        <div className="row">
          <NumberField
            id="temp"
            label="Temperature"
            value={config.temperature}
            onChange={(n) => set('temperature', n)}
            min={0}
            max={2}
            step="any"
          />
          <NumberField
            id="seed"
            label="Seed"
            value={config.seed}
            onChange={(n) => set('seed', n)}
            min={-2147483648}
            max={2147483647}
          />
          <NumberField
            id="repeats"
            label="Repeats"
            value={config.repeats}
            onChange={(n) => set('repeats', n)}
            min={1}
            max={20}
          />
          <NumberField
            id="ctx"
            label="Context size"
            value={config.num_ctx}
            onChange={(n) => set('num_ctx', n)}
            min={512}
            max={262144}
            step={512}
          />
          <NumberField
            id="maxtok"
            label="Max output tokens"
            value={config.max_output_tokens}
            onChange={(n) => set('max_output_tokens', n)}
            min={16}
            max={65536}
          />
        </div>
        <p className="small muted">
          Temperature 0 with a fixed seed makes runs reproducible. Repeats reduce timing noise.
        </p>
        <label className="check">
          <input
            type="checkbox"
            checked={config.think}
            onChange={(e) => set('think', e.target.checked)}
          />
          <span>Enable thinking on thinking-capable models</span>
        </label>
        <label className="check" style={{ marginTop: 8 }}>
          <input
            type="checkbox"
            checked={config.warmup}
            onChange={(e) => set('warmup', e.target.checked)}
          />
          <span>Warm up each model first (keeps load time out of the speed numbers)</span>
        </label>
      </fieldset>
    </section>
  );
}
