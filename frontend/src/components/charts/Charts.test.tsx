import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { columnPath, niceTicks, placeLabels, rowPath } from '../../lib/chartMath';
import { row, THREE_MODELS } from '../../test/fixtures';
import BarRanking from './BarRanking';
import ChartsSection from './ChartsSection';
import ScoreChart from './ScoreChart';
import TradeoffScatter from './TradeoffScatter';
import { seriesColor } from './Viz';

const withComposite = (rows = THREE_MODELS) =>
  rows.map((r, i) => ({ ...r, composite: [0.75, 0.667, 0.667][i] ?? 0.5 }));
const CATS = ['classification', 'reasoning', 'generation'] as const;

describe('chart math', () => {
  it('niceTicks rounds to clean values', () => {
    expect(niceTicks(1, 4)).toEqual([0, 0.5, 1]);
    expect(niceTicks(1900, 4)).toEqual([0, 500, 1000, 1500, 2000]);
    expect(niceTicks(0)).toEqual([0, 1]);
    expect(niceTicks(46, 5).at(-1)! >= 46).toBe(true);
  });

  it('bar paths have rounded data ends and square baselines', () => {
    const col = columnPath(10, 20, 24, 100);
    expect(col).toContain('a4,4'); // 4px radius
    expect(col.startsWith('M10,120')); // grows from the baseline (bottom)
    expect(rowPath(0, 0, 100, 24)).toContain('a4,4');
    expect(columnPath(0, 0, 24, 2)).toContain('a2,2'); // radius shrinks for tiny bars
    expect(columnPath(0, 0, 24, 0)).not.toContain('a'); // no arcs on zero height
  });

  it('placeLabels never overlaps labels or leaves the canvas', () => {
    const pts = [
      { x: 100, y: 100, text: 'alpha:1' },
      { x: 104, y: 102, text: 'bravo:2' },
      { x: 560, y: 100, text: 'charlie-with-a-long-name:3' },
    ];
    const out = placeLabels(pts, 640);
    const w = (t: string) => t.length * 6.6;
    const boxes = out.map((o, i) => {
      const width = w(pts[i].text);
      const left = o.anchor === 'start' ? o.x : o.anchor === 'end' ? o.x - width : o.x - width / 2;
      return { left, right: left + width, top: o.y - 11, bottom: o.y + 3 };
    });
    boxes.forEach((b) => {
      expect(b.left).toBeGreaterThanOrEqual(0);
      expect(b.right).toBeLessThanOrEqual(640);
    });
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i],
          b = boxes[j];
        expect(a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom).toBe(
          false,
        );
      }
  });

  it('assigns categorical slots in fixed order and folds past eight', () => {
    expect(seriesColor(0)).toBe('var(--series-1)');
    expect(seriesColor(7)).toBe('var(--series-8)');
    expect(seriesColor(8)).toBe('var(--series-other)');
  });
});

describe('ScoreChart', () => {
  const renderChart = (rows = THREE_MODELS) =>
    render(
      <ScoreChart
        rows={rows}
        categories={[...CATS]}
        colorIndex={(m) => rows.findIndex((r) => r.model === m)}
      />,
    );

  it('draws one column per model and category with model, category and value in its label', () => {
    renderChart();
    const bars = screen.getAllByTestId('score-bar');
    expect(bars).toHaveLength(9);
    expect(screen.getByRole('img', { name: 'alpha:1, Classification: 100%' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'bravo:2, Reasoning: 100%' })).toBeInTheDocument();
  });

  it('gives each model a fixed colour and a legend, so identity is not colour alone', () => {
    renderChart();
    const legend = screen.getByRole('list', { name: 'Legend' });
    expect(
      within(legend)
        .getAllByRole('listitem')
        .map((l) => l.textContent),
    ).toEqual(['alpha:1', 'bravo:2', 'charlie:3']);
    const fills = screen.getAllByTestId('score-bar').map((b) => b.getAttribute('fill'));
    expect(new Set(fills)).toEqual(
      new Set(['var(--series-1)', 'var(--series-2)', 'var(--series-3)']),
    );
    expect(fills.slice(0, 3)).toEqual(['var(--series-1)', 'var(--series-2)', 'var(--series-3)']); // same order in every group
  });

  it('labels only the best column per category, never every bar', () => {
    const { container } = renderChart();
    const values = [...container.querySelectorAll('text.value')].map((t) => t.textContent);
    expect(values).toEqual(['100%', '100%', '100%']); // one per category
  });

  it('marks unscored categories as n/a and omits the bar', () => {
    renderChart([
      row('a:1', { cls: 1, rea: 1, gen: null }),
      row('b:1', { cls: 0.5, rea: 0.5, gen: null }),
    ]);
    expect(screen.getAllByTestId('score-bar')).toHaveLength(4);
    expect(screen.getAllByText('n/a')).toHaveLength(2);
  });

  it('shows no legend for a single model', () => {
    renderChart([row('only:1', { cls: 1, rea: 1, gen: 1 })]);
    expect(screen.queryByRole('list', { name: 'Legend' })).toBeNull();
  });

  it('uses only recessive solid hairline grid lines (no dashes)', () => {
    const { container } = renderChart();
    expect(container.querySelectorAll('[stroke-dasharray]').length).toBe(0);
    expect(container.querySelectorAll('line.grid').length).toBeGreaterThan(0);
  });

  it('shows a tooltip on keyboard focus and hides it on Escape', async () => {
    const user = userEvent.setup();
    renderChart();
    fireEvent.focus(screen.getByRole('img', { name: 'alpha:1, Generation: 75%' }));
    const tip = await screen.findByRole('tooltip');
    expect(tip).toHaveTextContent('alpha:1');
    expect(tip).toHaveTextContent('Generation: 75%');
    expect(tip).toHaveTextContent('2/2 cases scored');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('has a table view twin with every value', async () => {
    const user = userEvent.setup();
    renderChart();
    await user.click(screen.getByText('Table view'));
    const table = screen.getByRole('table', { name: 'Score by category and model' });
    expect(
      within(table).getByRole('row', { name: /alpha:1 100% \(2\/2\) 50% \(2\/2\) 75% \(2\/2\)/ }),
    ).toBeInTheDocument();
  });
});

describe('BarRanking', () => {
  const items = [
    { model: 'slow:1', value: 12000, detail: [] },
    { model: 'fast:2', value: 1600, detail: ['p95 2 s'] },
    { model: 'nodata:3', value: null, detail: [] },
  ];
  const fmt = (v: number) => `${v} ms`;

  it('sorts best-first, labels each bar at its tip and lists models without data', () => {
    render(
      <BarRanking
        title="Median latency"
        subtitle="s"
        items={items}
        format={fmt}
        lowerIsBetter
        unit="Median latency"
      />,
    );
    expect(screen.getAllByTestId('rank-bar').map((b) => b.getAttribute('aria-label'))).toEqual([
      'fast:2: 1600 ms',
      'slow:1: 12000 ms',
    ]);
    expect(screen.getByText('No data: nodata:3')).toBeInTheDocument();
  });

  it('sorts descending when higher is better, using a single series colour', () => {
    render(
      <BarRanking
        title="Speed"
        subtitle="s"
        items={items}
        format={fmt}
        lowerIsBetter={false}
        unit="Tokens/s"
      />,
    );
    expect(screen.getAllByTestId('rank-bar').map((b) => b.getAttribute('aria-label'))).toEqual([
      'slow:1: 12000 ms',
      'fast:2: 1600 ms',
    ]);
    expect(new Set(screen.getAllByTestId('rank-bar').map((b) => b.getAttribute('fill')))).toEqual(
      new Set(['var(--series-1)']),
    );
  });

  it('handles the empty state and table view', async () => {
    const { rerender } = render(
      <BarRanking title="T" subtitle="s" items={[]} format={fmt} lowerIsBetter unit="u" />,
    );
    expect(screen.getByText('No measurements yet.')).toBeInTheDocument();
    rerender(
      <BarRanking title="T" subtitle="s" items={items} format={fmt} lowerIsBetter unit="Latency" />,
    );
    await userEvent.setup().click(screen.getByText('Table view'));
    expect(screen.getByRole('row', { name: /fast:2 1600 ms p95 2 s/ })).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /nodata:3 n\/a/ })).toBeInTheDocument();
  });
});

describe('TradeoffScatter', () => {
  it('labels every point with its model name so identity never relies on colour', () => {
    render(<TradeoffScatter rows={withComposite()} />);
    const labels = screen.getAllByTestId('tradeoff-label').map((l) => l.textContent);
    expect(labels.sort()).toEqual(['alpha:1', 'bravo:2', 'charlie:3']);
    expect(screen.getAllByTestId('tradeoff-point')).toHaveLength(3);
    expect(screen.getAllByTestId('tradeoff-point')[0].getAttribute('aria-label')).toMatch(
      /alpha:1: composite 75.0%, median latency 6.8 s/,
    );
  });

  it('switches the x-axis between latency and tokens per second', async () => {
    const user = userEvent.setup();
    render(<TradeoffScatter rows={withComposite()} />);
    expect(screen.getByText(/Median latency \(lower is faster\)/)).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Tokens per second' }));
    expect(screen.getByText(/Tokens per second \(higher is faster\)/)).toBeInTheDocument();
    expect(screen.getAllByTestId('tradeoff-point')[0].getAttribute('aria-label')).toMatch(
      /tokens per second 40/,
    );
  });

  it('lists models it cannot plot instead of dropping them silently', () => {
    const rows = withComposite([
      ...THREE_MODELS,
      row('nospeed:4', { cls: 1, rea: 1, gen: 1, latency: null, tps: null }),
    ]);
    render(<TradeoffScatter rows={rows} />);
    expect(screen.getAllByTestId('tradeoff-point')).toHaveLength(3);
    expect(screen.getByText(/Not plotted.*nospeed:4/)).toBeInTheDocument();
  });

  it('renders markers with a 2px surface ring and at least 8px diameter', () => {
    render(<TradeoffScatter rows={withComposite()} />);
    const dot = screen.getAllByTestId('tradeoff-point')[0];
    expect(Number(dot.getAttribute('r')) * 2).toBeGreaterThanOrEqual(8);
    expect(dot.getAttribute('stroke')).toBe('var(--viz-surface)');
    expect(dot.getAttribute('stroke-width')).toBe('2');
  });

  it('shows an empty state with nothing to plot', () => {
    render(
      <TradeoffScatter
        rows={withComposite([row('x:1', { cls: 1 })]).map((r) => ({ ...r, composite: null }))}
      />,
    );
    expect(screen.getByText(/Nothing to plot yet/)).toBeInTheDocument();
  });
});

describe('ChartsSection', () => {
  it('keeps each model on the same colour slot across charts and renders all three chart types', () => {
    render(<ChartsSection rows={withComposite()} categories={[...CATS]} />);
    expect(screen.getByRole('heading', { name: 'Score by category' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Median latency' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Generation speed' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Quality vs. speed' })).toBeInTheDocument();
    expect(screen.getAllByRole('img', { name: /^charlie:3, / })[0].getAttribute('fill')).toBe(
      'var(--series-3)',
    );
  });

  it('6.5: shows no local-vs-cloud note for an all-local comparison', () => {
    render(<ChartsSection rows={withComposite()} categories={[...CATS]} />);
    expect(screen.queryByText(/not directly like-for-like/)).toBeNull();
  });

  it('6.5: shows the local-vs-cloud latency note only when local and cloud models are both present', () => {
    const mixed = withComposite([
      ...THREE_MODELS,
      row('@oa/gpt-4o', { cls: 1, rea: 1, gen: 1, latency: 900, tps: 60, cloud: true }),
    ]);
    render(<ChartsSection rows={mixed} categories={[...CATS]} />);
    expect(screen.getByText(/include network time and provider queueing/)).toBeInTheDocument();
    expect(screen.getByText(/not directly like-for-like/)).toBeInTheDocument();
  });

  it('6.5: shows no note when every model is cloud', () => {
    const allCloud = withComposite([
      row('@oa/gpt-4o', { cls: 1, rea: 1, gen: 1, latency: 900, tps: 60, cloud: true }),
      row('@an/claude', { cls: 1, rea: 1, gen: 1, latency: 1100, tps: 55, cloud: true }),
    ]);
    render(<ChartsSection rows={allCloud} categories={[...CATS]} />);
    expect(screen.queryByText(/not directly like-for-like/)).toBeNull();
  });
});
