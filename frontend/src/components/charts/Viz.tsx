import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

/** Model -> categorical slot by its position in the run (fixed order, never by rank; > 8 fold to gray). */
export const seriesColor = (index: number) =>
  index < 8 ? `var(--series-${index + 1})` : 'var(--series-other)';

export function useChartWidth(fallback = 640): [React.RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const measure = () => setWidth(Math.max(320, Math.floor(el.clientWidth)) || fallback);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fallback]);
  return [ref, width];
}

export interface Tip {
  x: number;
  y: number;
  title: string;
  lines: string[];
}

export function useTip() {
  const [tip, setTip] = useState<Tip | null>(null);
  useEffect(() => {
    if (!tip) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setTip(null);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [tip]);
  return { tip, show: setTip, hide: () => setTip(null) };
}

export function TipBox({ tip }: { tip: Tip | null }) {
  if (!tip) return null;
  return (
    <div className="viz-tip" role="tooltip" style={{ left: tip.x, top: tip.y }}>
      <strong>{tip.title}</strong>
      {tip.lines.map((l) => (
        <div key={l}>{l}</div>
      ))}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  if (items.length < 2) return null; // a single series needs no legend; the title names it
  return (
    <ul className="viz-legend" aria-label="Legend">
      {items.map((i) => (
        <li key={i.label}>
          <span className="swatch" style={{ background: i.color }} aria-hidden="true" />
          {i.label}
        </li>
      ))}
    </ul>
  );
}

export function TableView({
  caption,
  head,
  rows,
}: {
  caption: string;
  head: string[];
  rows: ReactNode[][];
}) {
  return (
    <details className="viz-table">
      <summary>Table view</summary>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {head.map((h, i) => (
                <th key={h} className={i > 0 ? 'num' : undefined}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {r.map((c, j) => (
                  <td key={j} className={j > 0 ? 'num' : undefined}>
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function ChartFrame({
  title,
  subtitle,
  legend,
  children,
  table,
  tip,
  containerRef,
}: {
  title: string;
  subtitle?: string;
  legend?: ReactNode;
  children: ReactNode;
  table: ReactNode;
  tip: Tip | null;
  containerRef?: React.RefObject<HTMLDivElement>;
}) {
  return (
    <figure className="viz-root" style={{ margin: 0 }}>
      <figcaption>
        <h3 className="viz-title">{title}</h3>
        {subtitle && <p className="viz-sub">{subtitle}</p>}
      </figcaption>
      {legend}
      <div ref={containerRef} style={{ position: 'relative' }}>
        {children}
        <TipBox tip={tip} />
      </div>
      {table}
    </figure>
  );
}
