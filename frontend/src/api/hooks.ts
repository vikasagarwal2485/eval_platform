import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import type {
  CaseIn,
  CaseOut,
  AttentionItem,
  AvailableModel,
  Agent,
  AgentCreate,
  AgentSettingsUpdate,
  AgentSummary,
  AgentTurn,
  AgentTurnDetail,
  Compare,
  ConnectionTest,
  Health,
  JudgeMode,
  ModelInfo,
  Provider,
  ProviderCreate,
  ProviderModel,
  ResultsResponse,
  Run,
  RunCreate,
  RubricCriterion,
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
  providers: ['providers'] as const,
  agents: ['agents'] as const,
  agent: (id: number) => ['agent', id] as const,
  agentTurns: (id: number, sessionId?: string | null, status?: string | null) =>
    ['agent-turns', id, sessionId ?? '', status ?? ''] as const,
  agentTurn: (agentId: number, turnId: number) => ['agent-turn', agentId, turnId] as const,
  agentSummary: (id: number, window: string) => ['agent-summary', id, window] as const,
  agentAttention: (id: number, window: string) => ['agent-attention', id, window] as const,
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

// ---------------------------------------------------------------- providers (enterprise models)
export const useProviders = () =>
  useQuery({ queryKey: keys.providers, queryFn: () => api.get<Provider[]>('/providers') });

/** Anything that changes providers or their models also changes what Run setup can offer. */
function useProviderRefresh() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: keys.providers });
    qc.invalidateQueries({ queryKey: keys.models });
    qc.invalidateQueries({ queryKey: keys.health });
  };
}

export function useProviderMutations() {
  const refresh = useProviderRefresh();
  return {
    create: useMutation({
      mutationFn: (b: ProviderCreate) => api.post<Provider>('/providers', b),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, ...b }: { id: number; key_env?: string; base_url?: string }) =>
        api.patch<Provider>(`/providers/${id}`, b),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api.delete(`/providers/${id}`),
      onSuccess: refresh,
    }),
    addModel: useMutation({
      mutationFn: ({
        providerId,
        ...b
      }: {
        providerId: number;
        model_id: string;
        display_name?: string;
        reasoning?: boolean;
        enabled?: boolean;
      }) => api.post<ProviderModel>(`/providers/${providerId}/models`, b),
      onSuccess: refresh,
    }),
    updateModel: useMutation({
      mutationFn: ({
        providerId,
        modelId,
        ...b
      }: {
        providerId: number;
        modelId: number;
        enabled?: boolean;
        reasoning?: boolean;
        display_name?: string;
      }) => api.patch<ProviderModel>(`/providers/${providerId}/models/${modelId}`, b),
      onSuccess: refresh,
    }),
    removeModel: useMutation({
      mutationFn: ({ providerId, modelId }: { providerId: number; modelId: number }) =>
        api.delete(`/providers/${providerId}/models/${modelId}`),
      onSuccess: refresh,
    }),
    test: useMutation({
      mutationFn: (id: number) => api.post<ConnectionTest>(`/providers/${id}/test`),
    }),
    fetchModels: useMutation({
      mutationFn: (id: number) =>
        api.get<{ models: AvailableModel[] }>(`/providers/${id}/available-models`),
    }),
  };
}

// ---------------------------------------------------------------- agents (live evaluation)
export const useAgents = () =>
  useQuery({
    queryKey: keys.agents,
    queryFn: () => api.get<Agent[]>('/agents'),
    refetchInterval: 15_000, // rolling status/quality figures drift slowly; no SSE on the list page
  });

export const useAgent = (id: number) =>
  useQuery({ queryKey: keys.agent(id), queryFn: () => api.get<Agent>(`/agents/${id}`) });

export const useAgentTurns = (id: number, sessionId?: string | null, status?: string | null) =>
  useQuery({
    queryKey: keys.agentTurns(id, sessionId, status),
    queryFn: () => {
      const p = new URLSearchParams();
      if (sessionId) p.set('session_id', sessionId);
      if (status) p.set('status', status);
      const qs = p.toString();
      return api.get<AgentTurn[]>(`/agents/${id}/turns${qs ? `?${qs}` : ''}`);
    },
  });

export const useAgentTurn = (agentId: number, turnId: number | null) =>
  useQuery({
    queryKey: keys.agentTurn(agentId, turnId ?? -1),
    queryFn: () => api.get<AgentTurnDetail>(`/agents/${agentId}/turns/${turnId}`),
    enabled: turnId !== null,
  });

export const useAgentSummary = (id: number, window = '24h') =>
  useQuery({
    queryKey: keys.agentSummary(id, window),
    queryFn: () => api.get<AgentSummary>(`/agents/${id}/summary?window=${window}`),
    refetchInterval: 15_000,
  });

export const useAgentAttention = (id: number, window = '24h') =>
  useQuery({
    queryKey: keys.agentAttention(id, window),
    queryFn: () => api.get<AttentionItem[]>(`/agents/${id}/attention?window=${window}`),
  });

function useAgentRefresh(id?: number) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: keys.agents });
    if (id !== undefined) {
      qc.invalidateQueries({ queryKey: keys.agent(id) });
      qc.invalidateQueries({ queryKey: ['agent-turns', id] });
      qc.invalidateQueries({ queryKey: ['agent-summary', id] });
      qc.invalidateQueries({ queryKey: ['agent-attention', id] });
    }
  };
}

export function useCreateAgent() {
  const refresh = useAgentRefresh();
  return useMutation({
    mutationFn: (b: AgentCreate) => api.post<Agent>('/agents', b),
    onSuccess: refresh,
  });
}

export function useAgentMutations(id: number) {
  const refresh = useAgentRefresh(id);
  return {
    update: useMutation({
      mutationFn: (b: AgentSettingsUpdate) => api.patch<Agent>(`/agents/${id}`, b),
      onSuccess: refresh,
    }),
    pause: useMutation({
      mutationFn: () => api.post<Agent>(`/agents/${id}/pause`),
      onSuccess: refresh,
    }),
    resume: useMutation({
      mutationFn: () => api.post<Agent>(`/agents/${id}/resume`),
      onSuccess: refresh,
    }),
    rotateToken: useMutation({
      mutationFn: () => api.post<Agent>(`/agents/${id}/rotate-token`),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: () => api.delete(`/agents/${id}`),
      onSuccess: refresh,
    }),
  };
}

export function useEvaluateTurn(agentId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      turnId,
      evaluators,
      rubric,
    }: {
      turnId: number;
      evaluators?: string[];
      rubric?: RubricCriterion[];
    }) => api.post(`/agents/${agentId}/turns/${turnId}/evaluate`, { evaluators, rubric }),
    onSuccess: (_r, v) => {
      qc.invalidateQueries({ queryKey: keys.agentTurn(agentId, v.turnId) });
      qc.invalidateQueries({ queryKey: ['agent-turns', agentId] });
      qc.invalidateQueries({ queryKey: ['agent-summary', agentId] });
    },
  });
}

export function useReevaluateAgent(agentId: number) {
  const refresh = useAgentRefresh(agentId);
  return useMutation({
    mutationFn: (b: {
      since?: string;
      until?: string;
      below_score?: number;
      evaluators?: string[];
    }) => api.post<{ queued: number }>(`/agents/${agentId}/reevaluate`, b),
    onSuccess: refresh,
  });
}
