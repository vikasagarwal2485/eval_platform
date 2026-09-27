import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCreateRun, useHealth, useModels, useRefreshModels, useSuites } from '../api/hooks';
import type { CaseIn, JudgeMode, RunConfig } from '../api/types';
import { DEFAULT_RUN_CONFIG } from '../api/types';
import AdhocForm from '../components/AdhocForm';
import ConfigPanel from '../components/ConfigPanel';
import ModelPicker from '../components/ModelPicker';
import SaveToSuite from '../components/SaveToSuite';
import SuitePicker, { type SuiteSelection } from '../components/SuitePicker';
import { Banner, ErrorBox } from '../components/ui';

export default function RunSetupPage() {
  const navigate = useNavigate();
  const health = useHealth();
  const models = useModels();
  const suites = useSuites();
  const refresh = useRefreshModels();
  const create = useCreateRun();

  const [selected, setSelected] = useState<string[]>([]);
  const [suiteSel, setSuiteSel] = useState<SuiteSelection>({ suiteIds: [], excluded: {} });
  const [adhoc, setAdhoc] = useState<CaseIn[]>([]);
  const [tab, setTab] = useState<'suites' | 'adhoc'>('suites');
  const [config, setConfig] = useState<RunConfig>(DEFAULT_RUN_CONFIG);
  const [judge, setJudge] = useState<string | null>(null);
  const [judgeMode, setJudgeMode] = useState<JudgeMode>('none');
  const [judgeNotice, setJudgeNotice] = useState<string | null>(null);
  const [name, setName] = useState('');

  const suiteCaseCount = useMemo(
    () =>
      suiteSel.suiteIds.reduce((n, id) => {
        const s = suites.data?.find((x) => x.id === id);
        return n + (s ? s.case_count - (suiteSel.excluded[id]?.length ?? 0) : 0);
      }, 0),
    [suiteSel, suites.data],
  );
  const caseCount = suiteCaseCount + adhoc.length;
  const total = selected.length * caseCount * config.repeats;
  const countCategory = (cat: 'generation' | 'reasoning') =>
    adhoc.filter((c) => c.category === cat).length +
    suiteSel.suiteIds.reduce(
      (n, id) => n + (suites.data?.find((s) => s.id === id)?.counts_by_category[cat] ?? 0),
      0,
    );
  const caseCounts = {
    generation: countCategory('generation'),
    reasoning: countCategory('reasoning'),
  };

  // Cross-model judging needs two models: switch it off (and say so) if the selection later shrinks.
  useEffect(() => {
    if (judgeMode === 'cross_model' && selected.length < 2) {
      setJudgeMode('none');
      setJudgeNotice('Cross-model judging was switched off because it needs at least two models.');
    }
  }, [judgeMode, selected.length]);
  const changeJudgeMode = (m: JudgeMode) => {
    setJudgeMode(m);
    setJudgeNotice(null);
    if (m !== 'single') setJudge(null);
  };

  const ollamaDown = health.data ? !health.data.ollama.reachable : false;
  const backendDown = !!health.error;
  const all = models.data ?? [];
  const info = (ref: string) => all.find((m) => m.name === ref);
  // Ollama only matters if a local model is in the run (as contestant or single judge)
  const usesLocal = [...selected, ...(judgeMode === 'single' && judge ? [judge] : [])].some(
    (r) => (info(r)?.source ?? (r.startsWith('@') ? 'cloud' : 'local')) === 'local',
  );
  const unavailable = selected
    .map((r) => info(r))
    .filter((m): m is NonNullable<typeof m> => !!m && !m.available);
  const judgeInfo = judgeMode === 'single' && judge ? info(judge) : undefined;
  const blockers = [
    backendDown && 'The evaluation backend is not reachable.',
    ollamaDown && usesLocal && 'Ollama is unreachable, and this run uses a local model.',
    ...unavailable.map((m) => `${m.name} is unavailable: ${m.unavailable_reason}`),
    !selected.length && 'Select at least one model.',
    !caseCount && 'Select a test suite or add an ad-hoc prompt.',
    judgeMode === 'single' && !judge && 'Choose a judge model, or pick another judging mode.',
    judgeMode === 'single' &&
      !!judgeInfo &&
      !judgeInfo.available &&
      `Judge ${judgeInfo.name} is unavailable: ${judgeInfo.unavailable_reason}`,
  ].filter(Boolean) as string[];

  const start = () => {
    create.mutate(
      {
        name: name.trim() || undefined,
        models: selected,
        suite_ids: suiteSel.suiteIds,
        exclude_case_ids: Object.values(suiteSel.excluded).flat(),
        adhoc_cases: adhoc,
        config,
        judge_mode: judgeMode,
        judge_model: judgeMode === 'single' ? judge : null,
      },
      { onSuccess: (run) => navigate(`/runs/${run.id}/live`) },
    );
  };

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>Run setup</h1>
          <p className="muted">
            Pick models, choose what to send them, and compare accuracy, reasoning quality and
            speed.
          </p>
        </div>
      </div>

      {backendDown && (
        <Banner kind="error">Cannot reach the evaluation backend. Is it running?</Banner>
      )}
      {ollamaDown && (
        <Banner kind="error">
          <strong>Ollama unreachable</strong> at {health.data?.ollama.base_url}. Local models cannot
          be used until it is back; enterprise models still can.
        </Banner>
      )}

      <ModelPicker
        models={models.data}
        loading={models.isLoading}
        error={models.error}
        selected={selected}
        onChange={setSelected}
        onRefresh={() =>
          refresh.mutate(undefined, {
            onSuccess: (m) => setSelected((s) => s.filter((n) => m.some((x) => x.name === n))),
          })
        }
        ollamaDown={ollamaDown}
        ollamaUrl={health.data?.ollama.base_url}
        refreshing={refresh.isPending}
      />

      <section className="card" aria-labelledby="inputs-h" style={{ marginTop: 16 }}>
        <div className="card-head">
          <h2 id="inputs-h">2. What to send</h2>
          <span className="badge" aria-live="polite">
            {caseCount} {caseCount === 1 ? 'case' : 'cases'}
          </span>
        </div>
        <div className="tabs" role="tablist" aria-label="Input source">
          <button role="tab" aria-selected={tab === 'suites'} onClick={() => setTab('suites')}>
            Test suites
          </button>
          <button role="tab" aria-selected={tab === 'adhoc'} onClick={() => setTab('adhoc')}>
            Ad-hoc prompt{adhoc.length ? ` (${adhoc.length})` : ''}
          </button>
        </div>
        {tab === 'suites' ? (
          <SuitePicker value={suiteSel} onChange={setSuiteSel} />
        ) : (
          <div className="grid-2">
            <AdhocForm onAdd={(c) => setAdhoc((a) => [...a, c])} />
            <div>
              <h3>Prompts in this run</h3>
              {!adhoc.length && <p className="muted">None yet.</p>}
              <ul style={{ paddingLeft: 18 }}>
                {adhoc.map((c, i) => (
                  <li key={i}>
                    <span className="badge info">{c.category}</span> {c.prompt.slice(0, 90)}
                    {c.prompt.length > 90 ? '…' : ''}{' '}
                    <button
                      type="button"
                      className="link"
                      onClick={() => setAdhoc((a) => a.filter((_, j) => j !== i))}
                    >
                      Remove
                    </button>{' '}
                    <SaveToSuite item={c} />
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </section>

      <div style={{ marginTop: 16 }}>
        <ConfigPanel
          config={config}
          onChange={setConfig}
          judgeMode={judgeMode}
          onJudgeModeChange={changeJudgeMode}
          judgeModel={judge}
          onJudgeChange={setJudge}
          models={models.data ?? []}
          selectedModels={selected}
          caseCounts={caseCounts}
          totalCaseCount={caseCount}
          notice={judgeNotice}
          onDismissNotice={() => setJudgeNotice(null)}
        />
      </div>

      <section className="card" style={{ marginTop: 16 }} aria-label="Start">
        <div className="row">
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="run-name">Run name (optional)</label>
            <input
              id="run-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <span className="spacer" />
          <div>
            <strong>{total}</strong> requests{' '}
            <span className="muted small">
              ({selected.length} models × {caseCount} cases × {config.repeats} repeats)
            </span>
          </div>
          <button
            className="primary"
            disabled={blockers.length > 0 || create.isPending}
            onClick={start}
          >
            {create.isPending ? 'Starting…' : 'Start evaluation'}
          </button>
        </div>
        {blockers.length > 0 && (
          <ul className="small muted" style={{ margin: '8px 0 0', paddingLeft: 18 }}>
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        )}
        {create.error && (
          <div style={{ marginTop: 12 }}>
            <ErrorBox error={create.error} title="Could not start the run." />
          </div>
        )}
      </section>
    </>
  );
}
