import type { Category, LeaderRow } from '../../api/types';
import { columnPath, niceTicks } from '../../lib/chartMath';
import { fmtPct, titleCase } from '../../lib/format';
import { ChartFrame, Legend, TableView, seriesColor, useChartWidth, useTip } from './Viz';

const M = { top: 22, right: 8, bottom: 32, left: 44 };
const H = 300;
const MAX_BAR = 24;
const GAP = 2; // surface gap between touching bars

/** Grouped columns: one group per category, one column per model. Colour = model (fixed run order). */
export default function ScoreChart({
  rows,
  categories,
  colorIndex,
}: {
  rows: LeaderRow[];
  categories: Category[];
  colorIndex: (model: string) => number;
}) {
  const [ref, width] = useChartWidth();
  const { tip, show, hide } = useTip();
  const cats = categories.filter((c) => rows.some((r) => r.categories[c]));
  const innerW = width - M.left - M.right;
  const innerH = H - M.top - M.bottom;
  const band = innerW / Math.max(cats.length, 1);
  const m = rows.length;
  const slot = Math.min(band * 0.8, 200) / m; // per-model slot within the group
  const bw = Math.max(4, Math.min(MAX_BAR, slot - GAP));
  const y = (v: number) => M.top + innerH * (1 - v);
  const ticks = niceTicks(1, 4).filter((t) => t <= 1);

  return (
    <ChartFrame
      title="Score by category"
      subtitle="Share of cases answered correctly (classification, reasoning) or judged score (generation)."
      legend={
        <Legend
          items={rows.map((r) => ({ label: r.model, color: seriesColor(colorIndex(r.model)) }))}
        />
      }
      tip={tip}
      containerRef={ref}
      table={
        <TableView
          caption="Score by category and model"
          head={['Model', ...cats.map(titleCase)]}
          rows={rows.map((r) => [
            r.model,
            ...cats.map((c) => {
              const s = r.categories[c];
              return s?.score == null ? 'unscored' : `${fmtPct(s.score)} (${s.scored}/${s.total})`;
            }),
          ])}
        />
      }
    >
      <svg
        className="viz-svg"
        width={width}
        height={H}
        role="img"
        aria-label="Grouped column chart of score by category for each model"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              className={t === 0 ? 'axis' : 'grid'}
              x1={M.left}
              x2={width - M.right}
              y1={y(t)}
              y2={y(t)}
            />
            <text className="tick" x={M.left - 8} y={y(t) + 4} textAnchor="end">
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        {cats.map((c, ci) => {
          const gx = M.left + band * ci + (band - slot * m) / 2;
          const scores = rows.map((r) => r.categories[c]?.score ?? null);
          const best = Math.max(...scores.map((s) => s ?? -1));
          return (
            <g key={c}>
              <text x={M.left + band * ci + band / 2} y={H - 10} textAnchor="middle">
                {titleCase(c)}
              </text>
              {rows.map((r, ri) => {
                const info = r.categories[c];
                const score = info?.score ?? null;
                const x = gx + slot * ri + (slot - bw) / 2;
                const h = score === null ? 0 : Math.max(score * innerH, 2);
                const label = `${r.model}, ${titleCase(c)}: ${score === null ? 'unscored' : fmtPct(score)}`;
                const showTip = () =>
                  show({
                    x: x + bw / 2,
                    y: score === null ? y(0) - 4 : y(score),
                    title: r.model,
                    lines: [
                      `${titleCase(c)}: ${score === null ? 'unscored' : fmtPct(score)}`,
                      ...(info ? [`${info.scored}/${info.total} cases scored`] : []),
                      ...(info?.errors ? [`${info.errors} errors`] : []),
                    ],
                  });
                return (
                  <g key={r.model}>
                    {score !== null && (
                      <path
                        className="mark"
                        d={columnPath(x, y(0) - h, bw, h)}
                        fill={seriesColor(colorIndex(r.model))}
                        tabIndex={0}
                        role="img"
                        aria-label={label}
                        data-testid="score-bar"
                        onFocus={showTip}
                        onBlur={hide}
                      />
                    )}
                    {score === null && (
                      <text
                        className="tick"
                        x={x + bw / 2}
                        y={y(0) - 4}
                        textAnchor="middle"
                        aria-label={label}
                      >
                        n/a
                      </text>
                    )}
                    {score !== null && score === best && (
                      <text className="value" x={x + bw / 2} y={y(score) - 6} textAnchor="middle">
                        {fmtPct(score)}
                      </text>
                    )}
                    {/* generous hit target: whole slot, full plot height */}
                    <rect
                      className="hit"
                      x={gx + slot * ri}
                      y={M.top}
                      width={slot}
                      height={innerH}
                      onMouseEnter={showTip}
                      onMouseLeave={hide}
                    />
                  </g>
                );
              })}
            </g>
          );
        })}
        <line className="axis" x1={M.left} x2={width - M.right} y1={y(0)} y2={y(0)} />
      </svg>
    </ChartFrame>
  );
}
