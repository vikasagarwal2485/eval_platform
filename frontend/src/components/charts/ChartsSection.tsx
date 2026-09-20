import type { Category, LeaderRow } from '../../api/types';
import { fmtBytes, fmtMs, fmtNum } from '../../lib/format';
import BarRanking from './BarRanking';
import ScoreChart from './ScoreChart';
import TradeoffScatter from './TradeoffScatter';

type Row = LeaderRow & { composite: number | null };

export default function ChartsSection({
  rows,
  categories,
}: {
  rows: Row[];
  categories: Category[];
}) {
  // colour slot = position in the run's model list, so it never changes with sorting or filtering
  const order = rows.map((r) => r.model);
  const colorIndex = (m: string) => order.indexOf(m);
  const perf = (r: Row) => [
    `${r.performance.warm_requests} warm requests`,
    `p95 latency ${fmtMs(r.performance.latency_ms.p95)}`,
    `${fmtNum(r.performance.output_tokens.median, 0)} output tokens (median)`,
    ...(r.memory?.size ? [`memory ${fmtBytes(r.memory.size)}`] : []),
  ];
  return (
    <div className="stack" aria-label="Charts">
      <ScoreChart rows={rows} categories={categories} colorIndex={colorIndex} />
      <div className="grid-2">
        <BarRanking
          title="Median latency"
          subtitle="Time for a complete answer, warm requests only. Includes thinking time. Shorter is faster."
          items={rows.map((r) => ({
            model: r.model,
            value: r.performance.latency_ms.median,
            detail: perf(r),
          }))}
          format={(v) => fmtMs(v)}
          tickFormat={(v) => (v === 0 ? '0' : `${+(v / 1000).toFixed(2)} s`)}
          lowerIsBetter
          unit="Median latency"
        />
        <BarRanking
          title="Generation speed"
          subtitle="Tokens generated per second. Compare with output tokens: verbose models take longer at the same speed."
          items={rows.map((r) => ({
            model: r.model,
            value: r.performance.tokens_per_s.median,
            detail: perf(r),
          }))}
          format={(v) => fmtNum(v, v < 10 ? 1 : 0)}
          lowerIsBetter={false}
          unit="Tokens/s"
        />
      </div>
      <TradeoffScatter rows={rows} />
    </div>
  );
}
