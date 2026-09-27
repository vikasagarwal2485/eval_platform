import type { ReactNode } from 'react';
import { ApiError } from '../api/client';

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <span role="status" className="muted">
      <span className="spinner" aria-hidden="true" /> {label}…
    </span>
  );
}

export function Banner({
  kind,
  children,
  role,
}: {
  kind: 'error' | 'warn' | 'info';
  children: ReactNode;
  role?: string;
}) {
  return (
    <div className={`banner ${kind}`} role={role ?? (kind === 'error' ? 'alert' : 'status')}>
      {children}
    </div>
  );
}

export function ErrorBox({
  error,
  title,
  children,
}: {
  error: unknown;
  title?: string;
  children?: ReactNode;
}) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  const unreachable = error instanceof ApiError && error.code === 'ollama_unreachable';
  const baseUrl =
    error instanceof ApiError
      ? (error.detail as { base_url?: string } | undefined)?.base_url
      : undefined;
  return (
    <Banner kind="error">
      {title && <strong>{title} </strong>}
      {message}
      {children}
      {unreachable && (
        <div className="small">
          Ollama unreachable{baseUrl ? ` at ${baseUrl}` : ''}. Start it with{' '}
          <code>ollama serve</code>.
        </div>
      )}
    </Banner>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function CategoryBadge({ category }: { category: string }) {
  return <span className="badge info">{category}</span>;
}

const STATUS_KIND: Record<string, string> = {
  queued: '',
  running: 'info',
  completed: 'good',
  cancelled: 'warn',
  failed: 'bad',
};
export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${STATUS_KIND[status] ?? ''}`}>{status}</span>;
}

const OUTCOME_KIND: Record<string, string> = {
  correct: 'good',
  wrong: 'bad',
  unparseable: 'warn',
  error: 'bad',
  judged: 'info',
  pass: 'good',
  fail: 'bad',
};
/** Outcome text is always shown (never colour alone). */
export function OutcomeBadge({
  outcome,
  value,
}: {
  outcome: string | null | undefined;
  value?: number | null;
}) {
  const o = outcome ?? 'unscored';
  const text =
    o === 'judged' && value !== null && value !== undefined
      ? `judged ${Math.round(value * 100)}%`
      : o;
  return <span className={`badge ${OUTCOME_KIND[o] ?? ''}`}>{text}</span>;
}
