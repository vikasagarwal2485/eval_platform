import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { result, runOf } from '../test/fixtures';
import type { ResultItem } from '../api/types';
import CaseDrilldown from './CaseDrilldown';

const run = runOf(['alpha:1', 'bravo:2']);
const auto = (detail: Record<string, unknown>, outcome = 'correct') => ({
  kind: 'auto',
  value: outcome === 'correct' ? 1 : 0,
  outcome,
  detail,
});

function results(): ResultItem[] {
  return [
    result('alpha:1', 1, 'classification', 'correct', {
      output: 'spam',
      scores: [auto({ predicted: 'spam', ambiguous: false })],
    }),
    result('bravo:2', 1, 'classification', 'wrong', {
      output: 'not_spam',
      scores: [auto({ predicted: 'not_spam' }, 'wrong')],
    }),
    result('alpha:1', 2, 'reasoning', 'correct', {
      output: 'Final answer: 5',
      thinking: 'Let x be the ball...',
      scores: [auto({ final_answer: '5', method: 'marker' })],
      metrics: { thinking_tokens: 120, thinking_tokens_approx: true },
      latency_ms: 11200,
      output_tokens: 439,
    }),
    result('bravo:2', 2, 'reasoning', 'correct', {
      output: 'Final answer: 5',
      scores: [auto({ final_answer: '5', method: 'marker' })],
    }),
    result('alpha:1', 3, 'generation', 'judged', {
      output: 'Rain taps the window',
      primary: { value: 0.875, outcome: 'judged' },
      is_cold: true,
      scores: [
        {
          kind: 'judge',
          value: 0.875,
          outcome: 'judged',
          detail: {
            criteria: {
              Relevance: { score: 4, reason: 'on topic' },
              Fluency: { score: 5, reason: 'smooth' },
            },
            self_judged: true,
          },
        },
        {
          kind: 'constraints',
          value: 0,
          outcome: 'fail',
          detail: { checks: [{ name: 'max_words', passed: false, actual: 80, limit: 50 }] },
        },
      ],
    }),
    result('bravo:2', 3, 'generation', 'error', { error: 'timed out' }),
  ];
}

const caseCards = () => screen.getAllByRole('region').map((r) => r.getAttribute('aria-label'));

describe('9.8 case drill-down', () => {
  it('shows prompt, expected answer and every model side by side with scores and metrics', () => {
    render(<CaseDrilldown run={run} results={results()} />);
    const spam = screen.getByRole('region', { name: 'Case: Spam check' });
    expect(
      within(spam)
        .getByText(/Expected:/)
        .querySelector('code'),
    ).toHaveTextContent('spam');
    expect(within(spam).getByRole('heading', { name: 'alpha:1' })).toBeInTheDocument();
    expect(within(spam).getByRole('heading', { name: 'bravo:2' })).toBeInTheDocument();
    expect(within(spam).getByText('correct')).toBeInTheDocument();
    expect(within(spam).getByText('wrong')).toBeInTheDocument();
    expect(within(spam).getByText('not_spam', { selector: 'pre' })).toBeInTheDocument();
    expect(within(spam).getAllByText(/Predicted:/)).toHaveLength(2);
  });

  it('shows the prompt as sent, including the template version', async () => {
    render(<CaseDrilldown run={run} results={results()} />);
    const spam = screen.getByRole('region', { name: 'Case: Spam check' });
    await userEvent.setup().click(within(spam).getByText('Prompt'));
    expect(within(spam).getByText(/template v1/)).toBeInTheDocument();
    expect(within(spam).getAllByText('PROMPT + suffix').length).toBeGreaterThan(0);
  });

  it('keeps the reasoning trace collapsed until asked', async () => {
    const user = userEvent.setup();
    render(<CaseDrilldown run={run} results={results()} />);
    const card = screen.getByRole('region', { name: 'Case: Bat and ball' });
    const summary = within(card).getByText(/Reasoning trace \(20 chars\)/);
    const details = summary.closest('details')!;
    expect(details.open).toBe(false);
    await user.click(summary);
    expect(details.open).toBe(true);
    expect(within(card).getByText('Let x be the ball...')).toBeInTheDocument();
    await user.click(summary);
    expect(details.open).toBe(false);
  });

  it('shows extraction details and flags approximate thinking tokens', () => {
    render(<CaseDrilldown run={run} results={results()} />);
    const card = screen.getByRole('region', { name: 'Case: Bat and ball' });
    expect(within(card).getAllByText('5', { selector: 'code' }).length).toBeGreaterThan(0);
    expect(within(card).getAllByText('(marker)')).toHaveLength(2); // both models used the explicit marker
    expect(within(card).getByText(/439 tokens \(~120 thinking\)/)).toBeInTheDocument();
    expect(within(card).getByText('11.2 s', { exact: false })).toBeInTheDocument();
  });

  it('shows judge criteria with justification, self-judged flag, constraint failures, cold start and errors', () => {
    render(<CaseDrilldown run={run} results={results()} />);
    const card = screen.getByRole('region', { name: 'Case: Haiku' });
    expect(within(card).getByText(/Judge: 88% · self-judged/)).toBeInTheDocument();
    expect(within(card).getByText('Relevance')).toBeInTheDocument();
    expect(within(card).getByText('on topic')).toBeInTheDocument();
    expect(within(card).getByText('fail')).toBeInTheDocument();
    expect(within(card).getByText(/max_words 80\/50/)).toBeInTheDocument();
    expect(within(card).getByText('cold start')).toBeInTheDocument();
    expect(within(card).getByText('Error: timed out')).toBeInTheDocument();
  });

  it('filters to failures and back', async () => {
    const user = userEvent.setup();
    render(<CaseDrilldown run={run} results={results()} />);
    expect(caseCards()).toEqual(['Case: Spam check', 'Case: Bat and ball', 'Case: Haiku']);
    await user.click(screen.getByRole('checkbox', { name: /Only cases a model got wrong/ }));
    // bravo got the spam case wrong and errored on the haiku; the reasoning case is clean
    expect(caseCards()).toEqual(['Case: Spam check', 'Case: Haiku']);
    expect(screen.getByText('2 of 3 cases')).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: /Only cases a model got wrong/ }));
    expect(caseCards()).toHaveLength(3);
  });

  it('scopes the failure filter to one model and shows only that model', async () => {
    const user = userEvent.setup();
    render(<CaseDrilldown run={run} results={results()} />);
    await user.selectOptions(screen.getByLabelText('Model'), 'alpha:1');
    await user.click(screen.getByRole('checkbox', { name: /Only cases alpha:1 got wrong/ }));
    // alpha:1 only has a fine record -> nothing failed for it
    expect(screen.getByText('No matching cases')).toBeInTheDocument();
    expect(screen.getByText('Nothing failed for this selection.')).toBeInTheDocument();
  });

  it('filters by category', async () => {
    const user = userEvent.setup();
    render(<CaseDrilldown run={run} results={results()} />);
    await user.selectOptions(screen.getByLabelText('Category'), 'reasoning');
    expect(caseCards()).toEqual(['Case: Bat and ball']);
  });

  it('numbers repeats when a model answered a case several times', () => {
    const rs = [
      result('alpha:1', 1, 'classification', 'correct', { repeat: 0 }),
      result('alpha:1', 1, 'classification', 'wrong', { repeat: 1 }),
    ];
    render(<CaseDrilldown run={run} results={rs} />);
    expect(screen.getByText('Repeat 1')).toBeInTheDocument();
    expect(screen.getByText('Repeat 2')).toBeInTheDocument();
  });
});

describe('cross-model judging in the drill-down (5.5)', () => {
  const judgeScore = (
    value: number | null,
    outcome: 'judged' | 'error',
    judgements: object[],
    extra = {},
  ) => ({
    kind: 'judge',
    value,
    outcome,
    detail: {
      mode: 'cross_model',
      self_judged: false,
      judges_used: judgements.filter((j) => (j as { outcome: string }).outcome === 'judged').length,
      judgements,
      ...extra,
    },
  });
  const crit = (a: number, b: number, who: string) => ({
    Relevance: { score: a, reason: `${who}: on topic` },
    Fluency: { score: b, reason: `${who}: reads well` },
  });

  it('lists every judge with its score, criteria and reasons, plus the combined score', () => {
    const rs = [
      result('alpha:1', 3, 'generation', 'judged', {
        primary: { value: 0.625, outcome: 'judged' },
        scores: [
          judgeScore(0.625, 'judged', [
            {
              judge_model: 'bravo:2',
              value: 0.5,
              outcome: 'judged',
              criteria: crit(3, 3, 'bravo'),
            },
            {
              judge_model: 'charlie:3',
              value: 0.75,
              outcome: 'judged',
              criteria: crit(4, 4, 'charlie'),
            },
          ]),
        ],
      }),
    ];
    render(<CaseDrilldown run={run} results={rs} />);
    const card = screen.getByRole('region', { name: 'Case: Haiku' });
    expect(
      within(card).getByText(/Judge: 63% · cross-judged by 2 of 2 judges/),
    ).toBeInTheDocument();
    const list = within(card).getByRole('list', { name: 'Judge by judge' });
    const items = within(list)
      .getAllByRole('listitem')
      .filter((li) => li.querySelector('strong')?.textContent?.includes(':'));
    expect(items[0]).toHaveTextContent('bravo:2');
    expect(items[0]).toHaveTextContent('50%');
    expect(within(list).getByText('bravo: on topic')).toBeInTheDocument();
    expect(within(list).getByText('charlie: reads well')).toBeInTheDocument();
    expect(within(card).queryByText(/self-judged/)).toBeNull();
  });

  it('shows a failed judge alongside a successful one', () => {
    const rs = [
      result('alpha:1', 3, 'generation', 'judged', {
        primary: { value: 0.75, outcome: 'judged' },
        scores: [
          judgeScore(0.75, 'judged', [
            { judge_model: 'bravo:2', value: null, outcome: 'error', error: 'not valid JSON' },
            {
              judge_model: 'charlie:3',
              value: 0.75,
              outcome: 'judged',
              criteria: crit(4, 4, 'charlie'),
            },
          ]),
        ],
      }),
    ];
    render(<CaseDrilldown run={run} results={rs} />);
    const card = screen.getByRole('region', { name: 'Case: Haiku' });
    expect(within(card).getByText(/cross-judged by 1 of 2 judges/)).toBeInTheDocument();
    expect(within(card).getByText('failed')).toBeInTheDocument();
    expect(within(card).getByText('not valid JSON')).toBeInTheDocument();
    expect(within(card).getByText('charlie: on topic')).toBeInTheDocument();
  });

  it('says so when every judge failed, and keeps it open so the reasons are visible', () => {
    const rs = [
      result('alpha:1', 3, 'generation', 'error', {
        primary: { value: null, outcome: 'error' },
        scores: [
          judgeScore(
            null,
            'error',
            [{ judge_model: 'bravo:2', value: null, outcome: 'error', error: 'model not found' }],
            { error: 'bravo:2: model not found' },
          ),
        ],
      }),
    ];
    render(<CaseDrilldown run={run} results={rs} />);
    const card = screen.getByRole('region', { name: 'Case: Haiku' });
    expect(
      within(card).getByText(/all judges failed · cross-judged by 0 of 1 judge/),
    ).toBeInTheDocument();
    expect(within(card).getByText('model not found')).toBeVisible();
    expect(
      within(card)
        .getByText(/all judges failed/)
        .closest('details')!.open,
    ).toBe(true);
  });

  it('shows reasoning-quality judgements per judge too', () => {
    const rs = [
      result('alpha:1', 2, 'reasoning', 'correct', {
        scores: [
          {
            kind: 'auto',
            value: 1,
            outcome: 'correct',
            detail: { final_answer: '5', method: 'marker' },
          },
          {
            kind: 'judge_reasoning',
            value: 0.5,
            outcome: 'judged',
            detail: {
              mode: 'cross_model',
              judgements: [
                {
                  judge_model: 'bravo:2',
                  value: 0.5,
                  outcome: 'judged',
                  criteria: { Clarity: { score: 3, reason: 'a bit long' } },
                },
              ],
            },
          },
        ],
      }),
    ];
    render(<CaseDrilldown run={run} results={rs} />);
    const card = screen.getByRole('region', { name: 'Case: Bat and ball' });
    expect(
      within(card).getByText(/Reasoning quality: 50% · cross-judged by 1 of 1 judge/),
    ).toBeInTheDocument();
    expect(within(card).getByText('a bit long')).toBeInTheDocument();
  });
});
