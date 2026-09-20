import type { Category, CategoryScore, LeaderRow, ResultItem, Run, Summary } from '../api/types';

const stat = (median: number | null) => ({
  n: median === null ? 0 : 3,
  mean: median,
  median,
  p95: median,
  min: median,
  max: median,
  stdev: 0,
});

export const cat = (score: number | null, scored = 2, total = 2): CategoryScore => ({
  score,
  scored,
  total,
  errors: 0,
  unparseable: 0,
});

export function row(
  model: string,
  o: {
    cls?: number | null;
    rea?: number | null;
    gen?: number | null;
    latency?: number | null;
    tps?: number | null;
    ttft?: number | null;
    tokens?: number | null;
    self?: boolean;
    judges?: number | null;
    mem?: number | null;
  } = {},
): LeaderRow {
  const categories: Partial<Record<Category, CategoryScore>> = {};
  if (o.cls !== undefined) categories.classification = cat(o.cls);
  if (o.rea !== undefined) categories.reasoning = cat(o.rea);
  if (o.gen !== undefined) categories.generation = cat(o.gen, o.gen === null ? 0 : 2);
  return {
    model,
    model_id: 1,
    digest: 'd',
    parameter_size: '8B',
    quantization: 'Q4_K_M',
    categories,
    composite: null,
    performance: {
      requests: 6,
      warm_requests: 6,
      cold_requests: 0,
      latency_ms: stat(o.latency ?? null),
      ttft_ms: stat(o.ttft ?? 300),
      tokens_per_s: stat(o.tps ?? null),
      output_tokens: stat(o.tokens ?? 100),
      cold_load_ms: stat(null),
    },
    performance_by_category: {},
    memory: o.mem ? { size: o.mem, size_vram: o.mem } : null,
    classification: null,
    constraints: null,
    self_judged: !!o.self,
    judges_per_answer: o.judges ?? null,
    errors: 0,
  };
}

export const THREE_MODELS: LeaderRow[] = [
  row('alpha:1', { cls: 1, rea: 0.5, gen: 0.75, latency: 6800, tps: 40, tokens: 300 }),
  row('bravo:2', { cls: 0.5, rea: 1, gen: 0.5, latency: 1600, tps: 46, tokens: 60 }),
  row('charlie:3', { cls: 0.75, rea: 0.25, gen: 1, latency: 12000, tps: 20, tokens: 500 }),
];

export function summary(rows: LeaderRow[], extra: Partial<Summary> = {}): Summary {
  return {
    run_id: 5,
    status: 'completed',
    weights: { classification: 1, reasoning: 1, generation: 1 },
    include_cold: false,
    attempt: { id: 1, judge_model: 'judge:1', judge_mode: 'single' },
    attempts: [
      { id: 1, judge_model: 'judge:1', judge_mode: 'single', created_at: '2026-01-01T00:00:00Z' },
    ],
    judging: { mode: 'single', judges: [] },
    models_count: rows.length,
    comparable: rows.length > 1,
    categories_present: ['classification', 'reasoning', 'generation'],
    leaderboard: rows,
    ...extra,
  };
}

export function runOf(models: string[], extra: Partial<Run> = {}): Run {
  return {
    id: 5,
    name: 'Smoke',
    status: 'completed',
    config: {
      temperature: 0,
      seed: 42,
      max_output_tokens: 4096,
      num_ctx: 8192,
      repeats: 1,
      think: true,
      warmup: true,
      judge_reasoning: false,
    },
    judge_model: 'judge:1',
    judge_mode: 'single',
    models: models.map((name, i) => ({
      id: i + 1,
      name,
      digest: 'd',
      parameter_size: '8B',
      quantization: 'Q4',
      family: 'f',
      size_bytes: 1,
      thinking: false,
      memory: null,
    })),
    case_count: 2,
    progress: { completed: 4, total: 4 },
    error: null,
    ollama_version: '0.34.2',
    parent_run_id: null,
    created_at: '2026-01-01T00:00:00Z',
    started_at: '2026-01-01T00:00:00Z',
    finished_at: '2026-01-01T00:01:00Z',
    busy: false,
    cases: [
      {
        id: 1,
        position: 0,
        category: 'classification',
        title: 'Spam check',
        prompt: 'Is this spam? WIN NOW',
        system_prompt: null,
        expected: 'spam',
        config: { labels: ['spam', 'not_spam'] },
        rubric: null,
      },
      {
        id: 2,
        position: 1,
        category: 'reasoning',
        title: 'Bat and ball',
        prompt: 'Bat and ball problem',
        system_prompt: null,
        expected: '5',
        config: {},
        rubric: null,
      },
      {
        id: 3,
        position: 2,
        category: 'generation',
        title: 'Haiku',
        prompt: 'Write a haiku',
        system_prompt: null,
        expected: null,
        config: {},
        rubric: null,
      },
    ],
    ...extra,
  };
}

let nextId = 1;
export function result(
  model: string,
  caseId: number,
  category: Category,
  outcome: string,
  o: Partial<ResultItem> = {},
): ResultItem {
  return {
    id: nextId++,
    model,
    model_id: 1,
    case_id: caseId,
    category,
    repeat: 0,
    status: outcome === 'error' ? 'error' : 'ok',
    output: `${model} answer`,
    thinking: null,
    error: outcome === 'error' ? 'boom' : null,
    is_cold: false,
    sent_prompt: 'PROMPT + suffix',
    template_version: 'v1',
    latency_ms: 1500,
    ttft_ms: 300,
    tokens_per_s: 45.2,
    output_tokens: 50,
    metrics: {},
    scores: [],
    primary: { value: outcome === 'correct' ? 1 : 0, outcome },
    ...o,
  };
}
