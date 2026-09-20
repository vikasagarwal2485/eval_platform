import { niceTicks, rowPath, truncate } from '../../lib/chartMath';
import { ChartFrame, TableView, useChartWidth, useTip } from './Viz';

export interface RankItem {
  model: string;
  value: number | null;
  detail: string[]; // extra tooltip / table lines
}

const MAX_BAR = 24;
const ROW = 38;
const M = { top: 6, right: 64, bottom: 28 };

/** Horizontal bars for ONE measure (single series -> one colour). Sorted best-first. */
export default function BarRanking({
  title,
  subtitle,
  items,
  format,
  tickFormat,
  lowerIsBetter,
  unit,
}: {
  title: string;
  subtitle: string;
  items: RankItem[];
  format: (v: number) => string;
  /** axis tick labels; defaults to `format` */
  tickFormat?: (v: number) => string;
  lowerIsBetter: boolean;
  unit: string;
}) {
  const [ref, width] = useChartWidth();
  const { tip, show, hide } = useTip();
  const withVal = items
    .filter((i) => i.value !== null)
    .sort((a, b) => (lowerIsBetter ? a.value! - b.value! : b.value! - a.value!));
  const missing = items.filter((i) => i.value === null);
  const left = Math.min(
    190,
    Math.max(80, Math.max(...items.map((i) => Math.min(i.model.length, 26)), 0) * 7 + 12),
  );
  const innerW = Math.max(width - left - M.right, 40);
  const max = Math.max(...withVal.map((i) => i.value!), 0);
  const ticks = niceTicks(max, 4);
  const top = ticks[ticks.length - 1] || 1;
  const x = (v: number) => left + (innerW * v) / top;
  const H = M.top + withVal.length * ROW + M.bottom;

  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      tip={tip}
      containerRef={ref}
      table={
        <TableView
          caption={title}
          head={['Model', unit, 'Details']}
          rows={items.map((i) => [
            i.model,
            i.value === null ? 'n/a' : format(i.value),
            i.detail.join(' · '),
          ])}
        />
      }
    >
      {withVal.length === 0 ? (
        <p className="muted">No measurements yet.</p>
      ) : (
        <svg
          className="viz-svg"
          width={width}
          height={H}
          role="img"
          aria-label={`${title}: bar per model`}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line
                className={t === 0 ? 'axis' : 'grid'}
                x1={x(t)}
                x2={x(t)}
                y1={M.top}
                y2={H - M.bottom}
              />
              <text className="tick" x={x(t)} y={H - 10} textAnchor="middle">
                {(tickFormat ?? format)(t)}
              </text>
            </g>
          ))}
          {withVal.map((it, i) => {
            const y0 = M.top + i * ROW;
            const thick = Math.min(MAX_BAR, ROW - 14);
            const by = y0 + (ROW - thick) / 2;
            const len = Math.max(x(it.value!) - left, 2);
            const showTip = () =>
              show({
                x: left + len,
                y: by,
                title: it.model,
                lines: [`${unit}: ${format(it.value!)}`, ...it.detail],
              });
            return (
              <g key={it.model}>
                <text x={left - 10} y={by + thick / 2 + 4} textAnchor="end">
                  {truncate(it.model, 26)}
                  <title>{it.model}</title>
                </text>
                <path
                  className="mark"
                  d={rowPath(left, by, len, thick)}
                  fill="var(--series-1)"
                  tabIndex={0}
                  role="img"
                  aria-label={`${it.model}: ${format(it.value!)}`}
                  data-testid="rank-bar"
                  onFocus={showTip}
                  onBlur={hide}
                />
                <text className="value" x={left + len + 8} y={by + thick / 2 + 4}>
                  {format(it.value!)}
                </text>
                <rect
                  className="hit"
                  x={0}
                  y={y0}
                  width={width}
                  height={ROW}
                  onMouseEnter={showTip}
                  onMouseLeave={hide}
                />
              </g>
            );
          })}
        </svg>
      )}
      {missing.length > 0 && (
        <p className="small muted">No data: {missing.map((m) => m.model).join(', ')}</p>
      )}
    </ChartFrame>
  );
}
