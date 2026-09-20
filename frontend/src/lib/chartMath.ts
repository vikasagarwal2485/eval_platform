/** Pure geometry helpers for the SVG charts. */

/** ~`count` round tick values from 0 to a clean max >= `max` (e.g. 0, 1000, 2000). */
export function niceTicks(max: number, count = 4): number[] {
  if (!(max > 0)) return [0, 1];
  const rough = max / count;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const frac = rough / pow;
  const step = (frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10) * pow;
  const ticks: number[] = [];
  for (let v = 0; v < max + step * 0.999; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

/** Column with a rounded top (data end) and square base, growing from `y + h` (the baseline). */
export function columnPath(x: number, y: number, w: number, h: number, r = 4): string {
  const rr = Math.max(0, Math.min(r, h, w / 2));
  if (rr === 0) return `M${x},${y + h}H${x + w}V${y}H${x}Z`;
  return `M${x},${y + h}V${y + rr}a${rr},${rr} 0 0 1 ${rr},${-rr}H${x + w - rr}a${rr},${rr} 0 0 1 ${rr},${rr}V${y + h}Z`;
}

/** Horizontal bar with a rounded right end (data end) and square left base. */
export function rowPath(x: number, y: number, len: number, thick: number, r = 4): string {
  const rr = Math.max(0, Math.min(r, len, thick / 2));
  if (rr === 0) return `M${x},${y}H${x + len}V${y + thick}H${x}Z`;
  return `M${x},${y}H${x + len - rr}a${rr},${rr} 0 0 1 ${rr},${rr}V${y + thick - rr}a${rr},${rr} 0 0 1 ${-rr},${rr}H${x}Z`;
}

export interface LabelBox {
  x: number;
  y: number;
  anchor: 'start' | 'end' | 'middle';
}
interface Pt {
  x: number;
  y: number;
  text: string;
}

const CHAR_W = 6.6; // approx width of 12px UI text
const LABEL_H = 14;

function box(pt: Pt, pos: LabelBox) {
  const w = pt.text.length * CHAR_W;
  const left = pos.anchor === 'start' ? pos.x : pos.anchor === 'end' ? pos.x - w : pos.x - w / 2;
  return { left, right: left + w, top: pos.y - LABEL_H + 3, bottom: pos.y + 3 };
}
const overlap = (a: ReturnType<typeof box>, b: ReturnType<typeof box>) =>
  a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

/**
 * Place a direct label beside each point without overlap. Tries right, left, above, below in turn and
 * keeps labels inside [0, width]. Falls back to the first candidate (the legend/table still carry identity).
 */
export function placeLabels(points: Pt[], width: number, offset = 10): LabelBox[] {
  const placed: ReturnType<typeof box>[] = [];
  return points.map((p) => {
    const candidates: LabelBox[] = [
      { x: p.x + offset, y: p.y + 4, anchor: 'start' },
      { x: p.x - offset, y: p.y + 4, anchor: 'end' },
      { x: p.x, y: p.y - offset - 2, anchor: 'middle' },
      { x: p.x, y: p.y + offset + 12, anchor: 'middle' },
    ];
    const marks = points.map((q) => ({
      left: q.x - 7,
      right: q.x + 7,
      top: q.y - 7,
      bottom: q.y + 7,
    }));
    const fits = candidates.find((c) => {
      const b = box(p, c);
      return (
        b.left >= 0 &&
        b.right <= width &&
        !placed.some((o) => overlap(b, o)) &&
        !marks.some((m) => overlap(b, m))
      );
    });
    const chosen = fits ?? candidates[0];
    placed.push(box(p, chosen));
    return chosen;
  });
}

export const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
