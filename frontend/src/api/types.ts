export type Category = 'classification' | 'reasoning' | 'generation';
export const CATEGORIES: Category[] = ['classification', 'reasoning', 'generation'];

export interface ModelInfo {
  name: string;
  digest: string;
  size_bytes: number | null;
  parameter_size: string | null;
  quantization: string | null;
  family: string | null;
  capabilities: string[];
  thinking: boolean;
}

export interface Health {
  status: string;
  ollama: { reachable: boolean; base_url: string; version: string | null; error: string | null };
  config: { ollama_base_url: string; db_path: string; request_timeout_s: number };
}

// ---------------------------------------------------------------- cases & suites
export interface RubricCriterion {
  name: string;
  description?: string;
}
export interface Constraints {
  max_words?: number | null;
  min_words?: number | null;
  required_keywords?: string[];
  forbidden_keywords?: string[];
}
export interface CaseIn {
  category: Category;
  title?: string;
  prompt: string;
  system_prompt?: string | null;
  expected?: string | null;
  tags?: string[];
  labels?: string[];
  comparison?: 'text' | 'numeric';
  tolerance?: number;
  constraints?: Constraints | null;
  rubric?: RubricCriterion[] | null;
}
export interface CaseOut extends CaseIn {
  id: number;
  suite_id: number;
  position: number;
}
export interface Suite {
  id: number;
  name: string;
  description: string;
  is_builtin: boolean;
  case_count: number;
  counts_by_category: Partial<Record<Category, number>>;
}
export interface SuiteDetail extends Suite {
  cases: CaseOut[];
}

// ---------------------------------------------------------------- runs
export interface RunConfig {
  temperature: number;
  seed: number;
  max_output_tokens: number;
  num_ctx: number;
  repeats: number;
  think: boolean;
  warmup: boolean;
  request_timeout_s?: number | null;
  judge_reasoning: boolean;
}
export const DEFAULT_RUN_CONFIG: RunConfig = {
  temperature: 0,
  seed: 42,
  max_output_tokens: 4096,
  num_ctx: 8192,
  repeats: 1,
  think: true,
  warmup: true,
  request_timeout_s: null,
  judge_reasoning: false,
};

export type JudgeMode = 'none' | 'single' | 'cross_model';

export interface RunCreate {
  name?: string;
  models: string[];
  suite_ids?: number[];
  exclude_case_ids?: number[];
  case_ids?: number[];
  adhoc_cases?: CaseIn[];
  config?: Partial<RunConfig>;
  judge_model?: string | null;
  judge_mode?: JudgeMode;
}

export type RunStatus = 'queued' | 'running' | 'completed' | 'cancelled' | 'failed';
export interface Memory {
  size: number | null;
  size_vram: number | null;
}
export interface RunModel {
  id: number;
  name: string;
  digest: string;
  parameter_size: string | null;
  quantization: string | null;
  family: string | null;
  size_bytes: number | null;
  thinking: boolean;
  memory: Memory | null;
}
export interface RunCase {
  id: number;
  position: number;
  category: Category;
  title: string;
  prompt: string;
  system_prompt: string | null;
  expected: string | null;
  config: Record<string, unknown>;
  rubric: RubricCriterion[] | null;
}
export interface Run {
  id: number;
  name: string;
  status: RunStatus;
  config: RunConfig;
  judge_model: string | null;
  judge_mode: JudgeMode;
  models: RunModel[];
  case_count: number;
  progress: { completed: number; total: number };
  error: string | null;
  ollama_version: string | null;
  parent_run_id: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  cases?: RunCase[];
  current?: { model?: string; case_id?: number; case_title?: string; repeat?: number };
  busy?: boolean;
}

// ---------------------------------------------------------------- summary
export interface Stat {
  n: number;
  mean: number | null;
  median: number | null;
  p95: number | null;
  min: number | null;
  max: number | null;
  stdev: number | null;
}
export interface PerfStats {
  requests: number;
  warm_requests: number;
  cold_requests: number;
  latency_ms: Stat;
  ttft_ms: Stat;
  tokens_per_s: Stat;
  output_tokens: Stat;
  cold_load_ms: Stat;
}
export interface CategoryScore {
  score: number | null;
  scored: number;
  total: number;
  errors: number;
  unparseable: number;
}
export interface ClassificationMetrics {
  n: number;
  accuracy: number | null;
  unparseable: number;
  per_label: Record<
    string,
    { precision: number | null; recall: number | null; f1: number | null; support: number }
  >;
  confusion: { labels: string[]; rows: Record<string, Record<string, number>> } | null;
}
export interface LeaderRow {
  model: string;
  model_id: number;
  digest: string;
  parameter_size: string | null;
  quantization: string | null;
  categories: Partial<Record<Category, CategoryScore>>;
  composite: number | null;
  performance: PerfStats;
  performance_by_category: Partial<Record<Category, PerfStats>>;
  memory: Memory | null;
  classification: ClassificationMetrics | null;
  constraints: { passed: number; total: number } | null;
  self_judged: boolean;
  judges_per_answer: number | null;
  errors: number;
}
export type Weights = Record<Category, number>;
export interface JudgeStat {
  model: string;
  judged: number;
  errors: number;
  mean_score: number | null;
  reasoning_mean_score: number | null;
}
export interface Judgement {
  judge_model: string;
  value: number | null;
  outcome: 'judged' | 'error';
  criteria?: Record<string, { score: number; reason: string }>;
  raw_mean?: number;
  error?: string;
}

export interface Summary {
  run_id: number;
  status: RunStatus;
  weights: Weights;
  include_cold: boolean;
  attempt: { id: number; judge_model: string | null; judge_mode: JudgeMode } | null;
  attempts: { id: number; judge_model: string | null; judge_mode: JudgeMode; created_at: string }[];
  judging: { mode: JudgeMode; judges: JudgeStat[] };
  models_count: number;
  comparable: boolean;
  categories_present: Category[];
  leaderboard: LeaderRow[];
}

// ---------------------------------------------------------------- results
export interface ScoreRow {
  kind: string;
  value: number | null;
  outcome: string;
  detail: Record<string, unknown>;
}
export interface ResultItem {
  id: number;
  model: string;
  model_id: number;
  case_id: number;
  category: Category;
  repeat: number;
  status: 'ok' | 'error' | 'cancelled';
  output: string;
  thinking: string | null;
  error: string | null;
  is_cold: boolean;
  sent_prompt: string;
  template_version: string;
  latency_ms: number | null;
  ttft_ms: number | null;
  tokens_per_s: number | null;
  output_tokens: number | null;
  metrics: Record<string, number | boolean | null | Record<string, unknown>>;
  scores: ScoreRow[];
  primary: { value: number | null; outcome: string };
}
export interface ResultsResponse {
  attempt_id: number | null;
  results: ResultItem[];
}

// ---------------------------------------------------------------- compare
export interface Delta {
  a: number | null;
  b: number | null;
  delta: number | null;
}
export interface Compare {
  judging: { a: JudgeMode; b: JudgeMode; same: boolean };
  a: { id: number; name: string; status: string };
  b: { id: number; name: string; status: string };
  models: {
    model: string;
    same_digest: boolean;
    composite: Delta;
    categories: Partial<Record<Category, Delta>>;
    performance: Record<'latency_ms' | 'ttft_ms' | 'tokens_per_s', Delta>;
  }[];
  only_in_a: string[];
  only_in_b: string[];
  cases: {
    model: string;
    category: Category;
    title: string;
    a: number | null;
    b: number | null;
    delta: number | null;
  }[];
}

// ---------------------------------------------------------------- events
export interface ResultEvent {
  result_id: number;
  model: string;
  case_id: number;
  repeat: number;
  status: string;
  outcome: string | null;
  value: number | null;
  latency_ms: number | null;
  tokens_per_s: number | null;
  is_cold: boolean;
  error: string | null;
}
