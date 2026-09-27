import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

export type Handler = (req: { method: string; path: string; body: any }) => unknown; // eslint-disable-line @typescript-eslint/no-explicit-any

/** Stub `fetch` with a route table keyed "METHOD /path" (query string ignored unless keyed). */
export function mockApi(routes: Record<string, unknown | Handler>) {
  const calls: { method: string; path: string; body: any }[] = []; // eslint-disable-line @typescript-eslint/no-explicit-any
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace(/^\/api/, '');
    const method = (init?.method ?? 'GET').toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path: url, body });
    const key = [`${method} ${url}`, `${method} ${url.split('?')[0]}`].find((k) => k in routes);
    if (!key)
      return new Response(JSON.stringify({ detail: `no mock for ${method} ${url}` }), {
        status: 404,
      });
    const val = routes[key];
    const out = typeof val === 'function' ? (val as Handler)({ method, path: url, body }) : val;
    if (out instanceof Response) return out;
    return new Response(JSON.stringify(out), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fn);
  return { fn, calls };
}

export function jsonError(status: number, detail: unknown) {
  return new Response(JSON.stringify({ detail }), { status });
}

export function renderApp(ui: ReactElement, { route = '/', path = '*', stubLive = true } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return {
    qc,
    ...render(
      <QueryClientProvider client={qc}>
        <MemoryRouter
          initialEntries={[route]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Routes>
            <Route path={path} element={ui} />
            {stubLive && <Route path="/runs/:id/live" element={<div>LIVE PAGE</div>} />}
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

export const HEALTH_OK = {
  status: 'ok',
  ollama: { reachable: true, base_url: 'http://localhost:11434', version: '0.34.2', error: null },
  providers: [] as { name: string; kind: string; key_env: string; key_available: boolean }[],
  config: { ollama_base_url: 'http://localhost:11434', db_path: 'x', request_timeout_s: 300 },
};

const LOCAL = {
  source: 'local',
  provider: null,
  provider_kind: null,
  display_name: null,
  reasoning: false,
  available: true,
  unavailable_reason: null,
};
export const MODELS = [
  {
    name: 'gemma4:e4b',
    digest: 'd1',
    size_bytes: 9_600_000_000,
    parameter_size: '8.0B',
    quantization: 'Q4_K_M',
    family: 'gemma4',
    capabilities: ['completion', 'vision', 'thinking'],
    thinking: true,
    ...LOCAL,
  },
  {
    name: 'llama3:8b',
    digest: 'd2',
    size_bytes: 4_700_000_000,
    parameter_size: '8B',
    quantization: 'Q4_0',
    family: 'llama',
    capabilities: ['completion'],
    thinking: false,
    ...LOCAL,
  },
  {
    name: 'qwen3:8b',
    digest: 'd3',
    size_bytes: 5_200_000_000,
    parameter_size: '8.2B',
    quantization: 'Q4_K_M',
    family: 'qwen3',
    capabilities: ['completion', 'thinking'],
    thinking: true,
    ...LOCAL,
  },
];

/** Enterprise models as `/api/models` returns them. */
export const CLOUD_MODELS = [
  {
    name: '@oa/gpt-4o',
    digest: '',
    size_bytes: null,
    parameter_size: null,
    quantization: null,
    family: null,
    capabilities: ['completion'],
    thinking: false,
    source: 'cloud',
    provider: 'oa',
    provider_kind: 'openai',
    display_name: 'GPT-4o',
    reasoning: false,
    available: true,
    unavailable_reason: null,
  },
  {
    name: '@oa/o3',
    digest: '',
    size_bytes: null,
    parameter_size: null,
    quantization: null,
    family: null,
    capabilities: ['completion', 'thinking'],
    thinking: true,
    source: 'cloud',
    provider: 'oa',
    provider_kind: 'openai',
    display_name: 'o3',
    reasoning: true,
    available: true,
    unavailable_reason: null,
  },
  {
    name: '@an/claude',
    digest: '',
    size_bytes: null,
    parameter_size: null,
    quantization: null,
    family: null,
    capabilities: ['completion'],
    thinking: false,
    source: 'cloud',
    provider: 'an',
    provider_kind: 'anthropic',
    display_name: 'claude',
    reasoning: false,
    available: false,
    unavailable_reason: 'API key not set: environment variable AN_KEY is empty',
  },
];

export const SUITES = [
  {
    id: 1,
    name: 'Starter suite',
    description: 'Built in',
    is_builtin: true,
    case_count: 3,
    counts_by_category: { classification: 1, reasoning: 1, generation: 1 },
  },
];
export const SUITE_DETAIL = {
  ...SUITES[0],
  cases: [
    {
      id: 10,
      suite_id: 1,
      position: 0,
      category: 'classification',
      title: 'Sentiment',
      prompt: 'Great!',
      labels: ['positive', 'negative'],
      expected: 'positive',
    },
    {
      id: 11,
      suite_id: 1,
      position: 1,
      category: 'reasoning',
      title: 'Bat and ball',
      prompt: '...',
      expected: '5',
      comparison: 'numeric',
    },
    {
      id: 12,
      suite_id: 1,
      position: 2,
      category: 'generation',
      title: 'Haiku',
      prompt: 'Write a haiku',
    },
  ],
};

export const baseRoutes = {
  'GET /health': HEALTH_OK,
  'GET /models': MODELS,
  'GET /providers': [],
  'GET /suites': SUITES,
  'GET /suites/1': SUITE_DETAIL,
};
