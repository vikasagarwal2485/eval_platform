import { useState } from 'react';
import type { LeaderRow } from '../../api/types';
import { niceTicks, placeLabels } from '../../lib/chartMath';
import { fmtMs, fmtNum, fmtPct } from '../../lib/format';
import { ChartFrame, TableView, useChartWidth, useTip } from './Viz';

type XKey = 'latency' | 'tps';
const H = 340;
const M = { top: 16, right: 28, bottom: 52, left: 52 };

const X_OPTS: Record<
  XKey,
  {
    label: string;
    hint: string;
    get: (r: LeaderRow) => number | null;
    fmt: (v: number) => string;
    conv: (v: number) => number;
  }
> = {
  latency: {
    label: 'Median latency',
    hint: 'lower is faster',
    get: (r) => r.performance.latency_ms.median,
    fmt: (v) => `${fmtNum(v, v < 10 ? 1 : 0)} s`,
    conv: (ms) => ms / 1000,
  },
  tps: {
    label: 'Tokens per second',
    hint: 'higher is faster',
    get: (r) => r.performance.tokens_per_s.median,
    fmt: (v) => fmtNum(v, 0),
    conv: (v) => v,
  },
};

/** Quality vs. speed. One series (each point is a model) -> one colour; identity is carried by direct labels. */
export default function TradeoffScatter({
  rows,
}: {
  rows: (LeaderRow & { composite: number | null })[];
}) {
  const [xKey, setXKey] = useState<XKey>('latency');
  const [ref, width] = useChartWidth();
  const { tip, show, hide } = useTip();
  const opt = X_OPTS[xKey];

  const pts = rows.flatMap((r) => {
    const raw = opt.get(r);
    return raw === null || r.composite === null
      ? []
      : [{ model: r.model, x: opt.conv(raw), y: r.composite, row: r }];
  });
  const skipped = rows.filter((r) => !pts.some((p) => p.model === r.model));

  const innerW = width - M.left - M.right;
  const innerH = H - M.top - M.bottom;
  const xTicks = niceTicks(Math.max(...pts.map((p) => p.x), 0.001), 5);
  const xMax = xTicks[xTicks.length - 1] || 1;
  const sx = (v: number) => M.left + (innerW * v) / xMax;
  const sy = (v: number) => M.top + innerH * (1 - v);
  const yTicks = [0, 0.25, 0.5, 0.75, 1];
  const placed = pts.map((p) => ({ x: sx(p.x), y: sy(p.y), text: p.model }));
  const labels = placeLabels(placed, width);

  return (
    <ChartFrame
      title="Quality vs. speed"
      subtitle={`Each point is a model. Higher is more accurate; ${opt.hint} to the ${xKey === 'latency' ? 'left' : 'right'}. Top-${xKey === 'latency' ? 'left' : 'right'} is best.`}
      tip={tip}
      containerRef={ref}
      table={
        <TableView
          caption="Composite score and speed per model"
          head={['Model', 'Composite', opt.label]}
          rows={rows.map((r) => {
            const raw = opt.get(r);
            return [r.model, fmtPct(r.composite, 1), raw === null ? 'n/a' : opt.fmt(opt.conv(raw))];
          })}
        />
      }
    >
      <fieldset className="viz-ctrl" style={{ border: 0, padding: 0 }}>
        <legend className="sr-only">Speed measure</legend>
        {(Object.keys(X_OPTS) as XKey[]).map((k) => (
          <label key={k}>
            <input
              type="radio"
              name="tradeoff-x"
              checked={xKey === k}
              onChange={() => setXKey(k)}
            />{' '}
            {X_OPTS[k].label}
          </label>
        ))}
      </fieldset>
      {pts.length === 0 ? (
        <p className="muted">
          Nothing to plot yet: needs a composite score and a speed measurement.
        </p>
      ) : (
        <svg
          className="viz-svg"
          width={width}
          height={H}
          role="img"
          aria-label={`Scatter plot of composite score against ${opt.label.toLowerCase()}`}
        >
          {yTicks.map((t) => (
            <g key={t}>
              <line
                className={t === 0 ? 'axis' : 'grid'}
                x1={M.left}
                x2={width - M.right}
                y1={sy(t)}
                y2={sy(t)}
              />
              <text className="tick" x={M.left - 8} y={sy(t) + 4} textAnchor="end">
                {Math.round(t * 100)}%
              </text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={t} className="tick" x={sx(t)} y={H - M.bottom + 18} textAnchor="middle">
              {opt.fmt(t)}
            </text>
          ))}
          <line className="axis" x1={M.left} x2={width - M.right} y1={sy(0)} y2={sy(0)} />
          <text x={M.left + innerW / 2} y={H - 8} textAnchor="middle">
            {opt.label} ({opt.hint})
          </text>
          <text transform={`translate(14 ${M.top + innerH / 2}) rotate(-90)`} textAnchor="middle">
            Composite score
          </text>
          {pts.map((p, i) => {
            const cx = sx(p.x);
            const cy = sy(p.y);
            const showTip = () =>
              show({
                x: cx,
                y: cy - 4,
                title: p.model,
                lines: [
                  `Composite: ${fmtPct(p.y, 1)}`,
                  `${opt.label}: ${opt.fmt(p.x)}`,
                  `Latency: ${fmtMs(p.row.performance.latency_ms.median)} · ${fmtNum(p.row.performance.tokens_per_s.median)} tok/s`,
                ],
              });
            const l = labels[i];
            return (
              <g key={p.model}>
                {/* 8px+ marker with a 2px surface ring; larger transparent hit target */}
                <circle
                  className="mark"
                  cx={cx}
                  cy={cy}
                  r={6}
                  fill="var(--series-1)"
                  stroke="var(--viz-surface)"
                  strokeWidth={2}
                  tabIndex={0}
                  role="img"
                  aria-label={`${p.model}: composite ${fmtPct(p.y, 1)}, ${opt.label.toLowerCase()} ${opt.fmt(p.x)}`}
                  data-testid="tradeoff-point"
                  onFocus={showTip}
                  onBlur={hide}
                />
                <circle
                  className="hit"
                  cx={cx}
                  cy={cy}
                  r={14}
                  onMouseEnter={showTip}
                  onMouseLeave={hide}
                />
                <text
                  className="value"
                  x={l.x}
                  y={l.y}
                  textAnchor={l.anchor}
                  data-testid="tradeoff-label"
                >
                  {p.model}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      {skipped.length > 0 && (
        <p className="small muted">
          Not plotted (missing score or speed): {skipped.map((s) => s.model).join(', ')}
        </p>
      )}
    </ChartFrame>
  );
}
