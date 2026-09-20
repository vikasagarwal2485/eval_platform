import type { Category, CategoryScore, LeaderRow, Weights } from '../api/types';
import { CATEGORIES } from '../api/types';

export const EQUAL_WEIGHTS: Weights = { classification: 1, reasoning: 1, generation: 1 };

/** Same rule as the server: weighted mean over categories that have a score; weights renormalized. */
export function composite(
  cats: Partial<Record<Category, CategoryScore>>,
  weights: Weights,
): number | null {
  let num = 0;
  let den = 0;
  for (const c of CATEGORIES) {
    const s = cats[c]?.score;
    const w = Math.max(weights[c] ?? 0, 0);
    if (s === null || s === undefined || w === 0) continue;
    num += w * s;
    den += w;
  }
  return den ? num / den : null;
}

export function withComposite(
  rows: LeaderRow[],
  weights: Weights,
): (LeaderRow & { composite: number | null })[] {
  return rows.map((r) => ({ ...r, composite: composite(r.categories, weights) }));
}
