export const dash = '—';

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return dash;
  return ms >= 10_000
    ? `${(ms / 1000).toFixed(1)} s`
    : ms >= 1000
      ? `${(ms / 1000).toFixed(2)} s`
      : `${Math.round(ms)} ms`;
}
export function fmtNum(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined ? dash : n.toFixed(digits);
}
export function fmtPct(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? dash : `${(v * 100).toFixed(digits)}%`;
}
export function fmtBytes(b: number | null | undefined): string {
  if (b === null || b === undefined) return dash;
  const gb = b / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(b / 1024 ** 2).toFixed(0)} MB`;
}
export function fmtDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : dash;
}
export function fmtDuration(startIso: string | null, endIso: string | null): string {
  if (!startIso || !endIso) return dash;
  const s = (new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000;
  return s >= 90 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${s.toFixed(1)} s`;
}
export const titleCase = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
