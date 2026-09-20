export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
  get code(): string | undefined {
    const d = this.detail as { code?: string } | undefined;
    return d && typeof d === 'object' ? d.code : undefined;
  }
}

/** Turn FastAPI/Pydantic/custom error bodies into one readable line. */
export function describeError(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail ?? body;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e: { loc?: (string | number)[]; msg?: string }) => {
        const where = (e.loc ?? []).filter((p) => p !== 'body').join('.');
        return where ? `${where}: ${e.msg}` : String(e.msg);
      })
      .join('; ');
  }
  if (detail && typeof detail === 'object') {
    const d = detail as { message?: string; errors?: { field: string; message: string }[] };
    if (d.errors?.length) return d.errors.map((e) => `${e.field}: ${e.message}`).join('; ');
    if (d.message) return d.message;
  }
  return `Request failed (${status})`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'Cannot reach the evaluation backend', { code: 'backend_unreachable' });
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = undefined;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = text;
  }
  if (!res.ok)
    throw new ApiError(
      res.status,
      describeError(res.status, data),
      (data as { detail?: unknown })?.detail,
    );
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  delete: <T = void>(path: string) => request<T>('DELETE', path),
};
