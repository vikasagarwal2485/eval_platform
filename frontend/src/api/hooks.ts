import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import type {
  CaseIn,
  CaseOut,
  Compare,
  Health,
  JudgeMode,
  ModelInfo,
  ResultsResponse,
  Run,
  RunCreate,
  Suite,
  SuiteDetail,
  Summary,
  Weights,
} from './types';

export const ACTIVE_STATUSES = ['queued', 'running'];

export const keys = {
  health: ['health'] as const,
  models: ['models'] as const,
  suites: ['suites'] as const,
  suite: (id: number) => ['suite', id] as const,
  runs: ['runs'] as const,
  run: (id: number) => ['run', id] as const,
  summary: (id: number, w?: string, cold?: boolean, attempt?: number | null) =>
    ['summary', id, w ?? '', !!cold, attempt ?? null] as const,
  results: (id: number, attempt?: number | null) => ['results', id, attempt ?? null] as const,
  compare: (a: number, b: number) => ['compare', a, b] as const,
};

export function weightsParam(w?: Weights | null): string | undefined {
  return w
    ? Object.entries(w)
        .map(([k, v]) => `${k}:${v}`)
        .join(',')
    : undefined;
}

export const useHealth = () =>
  useQuery({
    queryKey: keys.health,
    queryFn: () => api.get<Health>('/health'),
    refetchInterval: 15_000,
  });

export const useModels = () =>
  useQuery({ queryKey: keys.models, queryFn: () => api.get<ModelInfo[]>('/models') });

export function useRefreshModels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.get<ModelInfo[]>('/models?refresh=1'),
    onSuccess: (models) => {
      qc.setQueryData(keys.models, models);
      qc.invalidateQueries({ queryKey: keys.health });
    },
  });
}

export const useSuites = () =>
  useQuery({ queryKey: keys.suites, queryFn: () => api.get<Suite[]>('/suites') });

export const useSuite = (id: number | null) =>
  useQuery({
    queryKey: keys.suite(id ?? -1),
    queryFn: () => api.get<SuiteDetail>(`/suites/${id}`),
    enabled: id !== null,
  });

export const useRuns = () =>
  useQuery({
    queryKey: keys.runs,
    queryFn: () => api.get<Run[]>('/runs'),
    refetchInterval: (q) =>
      q.state.data?.some((r) => ACTIVE_STATUSES.includes(r.status)) ? 3000 : false,
  });

/** Polls while the run is active: the DB is the source of truth, SSE only adds immediacy. */
export const useRun = (id: number) =>
  useQuery({
    queryKey: keys.run(id),
    queryFn: () => api.get<Run>(`/runs/${id}`),
    refetchInterval: (q) => {
      const r = q.state.data;
      return r && (ACTIVE_STATUSES.includes(r.status) || r.busy) ? 2500 : false;
    },
  });

export const useSummary = (
  id: number,
  opts: {
    weights?: Weights | null;
    includeCold?: boolean;
    attempt?: number | null;
    enabled?: boolean;
  } = {},
) => {
  const w = weightsParam(opts.weights);
  return useQuery({
    queryKey: keys.summary(id, w, opts.includeCold, opts.attempt),
    queryFn: () => {
      const p = new URLSearchParams();
      if (w) p.set('weights', w);
      if (opts.includeCold) p.set('include_cold', 'true');
      if (opts.attempt) p.set('attempt', String(opts.attempt));
      const qs = p.toString();
      return api.get<Summary>(`/runs/${id}/summary${qs ? `?${qs}` : ''}`);
    },
    enabled: opts.enabled ?? true,
    placeholderData: (prev) => prev, // keep the table on screen while weights change
  });
};

export const useResults = (id: number, attempt?: number | null, enabled = true) =>
  useQuery({
    queryKey: keys.results(id, attempt),
    queryFn: () =>
      api.get<ResultsResponse>(`/runs/${id}/results${attempt ? `?attempt=${attempt}` : ''}`),
    enabled,
  });

export const useCompare = (a: number | null, b: number | null) =>
  useQuery({
    queryKey: keys.compare(a ?? -1, b ?? -1),
    queryFn: () => api.get<Compare>(`/runs/compare?a=${a}&b=${b}`),
    enabled: a !== null && b !== null,
  });

// ---------------------------------------------------------------- mutations
export function useCreateRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: RunCreate) => api.post<Run>('/runs', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.runs }),
  });
}

export function useRunActions(id: number) {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.run(id) });
    qc.invalidateQueries({ queryKey: keys.runs });
  };
  return {
    cancel: useMutation({ mutationFn: () => api.post(`/runs/${id}/cancel`), onSuccess: refresh }),
    rescore: useMutation({
      mutationFn: (b: {
        judge_model: string | null;
        judge_mode?: JudgeMode;
        judge_reasoning?: boolean;
      }) => api.post(`/runs/${id}/rescore`, b),
      onSuccess: refresh,
    }),
  };
}

export function useRunMutations() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: keys.runs });
  return {
    rerun: useMutation({
      mutationFn: (id: number) => api.post<Run>(`/runs/${id}/rerun`),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api.delete(`/runs/${id}`),
      onSuccess: refresh,
    }),
  };
}

export function useSuiteMutations() {
  const qc = useQueryClient();
  const refresh = (id?: number) => {
    qc.invalidateQueries({ queryKey: keys.suites });
    if (id) qc.invalidateQueries({ queryKey: keys.suite(id) });
  };
  return {
    create: useMutation({
      mutationFn: (b: { name: string; description?: string; cases?: CaseIn[] }) =>
        api.post<SuiteDetail>('/suites', b),
      onSuccess: () => refresh(),
    }),
    update: useMutation({
      mutationFn: ({ id, ...b }: { id: number; name?: string; description?: string }) =>
        api.patch<SuiteDetail>(`/suites/${id}`, b),
      onSuccess: (s) => refresh(s.id),
    }),
    remove: useMutation({
      mutationFn: (id: number) => api.delete(`/suites/${id}`),
      onSuccess: () => refresh(),
    }),
    duplicate: useMutation({
      mutationFn: (id: number) => api.post<SuiteDetail>(`/suites/${id}/duplicate`),
      onSuccess: () => refresh(),
    }),
    addCase: useMutation({
      mutationFn: ({ suiteId, c }: { suiteId: number; c: CaseIn }) =>
        api.post<CaseOut>(`/suites/${suiteId}/cases`, c),
      onSuccess: (_r, v) => refresh(v.suiteId),
    }),
    updateCase: useMutation({
      mutationFn: ({ id, c }: { id: number; c: CaseIn; suiteId: number }) =>
        api.put<CaseOut>(`/cases/${id}`, c),
      onSuccess: (_r, v) => refresh(v.suiteId),
    }),
    deleteCase: useMutation({
      mutationFn: ({ id }: { id: number; suiteId: number }) => api.delete(`/cases/${id}`),
      onSuccess: (_r, v) => refresh(v.suiteId),
    }),
    importSuite: useMutation({
      mutationFn: (b: { content: string; name?: string }) =>
        api.post<SuiteDetail>('/suites/import', b),
      onSuccess: () => refresh(),
    }),
    saveAdhoc: useMutation({
      mutationFn: (b: { case: CaseIn; suite_id?: number; new_suite_name?: string }) =>
        api.post<CaseOut>('/suites/save-adhoc', b),
      onSuccess: () => refresh(),
    }),
  };
}
