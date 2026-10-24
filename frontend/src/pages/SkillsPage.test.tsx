import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { jsonError, mockApi, renderApp } from '../test/utils';
import SkillsPage from './SkillsPage';

afterEach(() => vi.unstubAllGlobals());

const SKILL_A = {
  id: 1,
  name: 'step-by-step',
  description: 'Think before answering',
  instructions: 'Think step by step, then give the final answer.',
  created_at: '2026-01-01T00:00:00+00:00',
};
const SKILL_B = {
  id: 2,
  name: 'concise',
  description: '',
  instructions: 'Answer in one sentence.',
  created_at: '2026-01-02T00:00:00+00:00',
};

/** Mirrors the registry: POST/PATCH/DELETE mutate a backing list that GET /skills re-reads, so a
 * component test can assert the page reflects a mutation after react-query refetches it - the
 * same way the real API would. Pass a function for an override to simulate a server error instead. */
function skillsSetup(
  initial: (typeof SKILL_A)[] = [SKILL_A],
  overrides: Record<string, unknown> = {},
) {
  const skills = [...initial];
  let nextId = Math.max(0, ...skills.map((s) => s.id)) + 1;
  const api = mockApi({
    'GET /skills': () => skills,
    'POST /skills': ({
      body,
    }: {
      body: { name: string; description?: string; instructions: string };
    }) => {
      const s = { id: nextId++, description: '', created_at: '2026-01-03T00:00:00+00:00', ...body };
      skills.push(s);
      return s;
    },
    'POST /skills/import': ({ body }: { body: { content: string } }) => {
      const [name, description, ...rest] = body.content.split('\n\n').filter(Boolean);
      const s = {
        id: nextId++,
        name,
        description: description ?? '',
        instructions: rest.join('\n\n'),
        created_at: '2026-01-03T00:00:00+00:00',
      };
      skills.push(s);
      return s;
    },
    'PATCH /skills/1': ({ body }: { body: Record<string, unknown> }) => {
      Object.assign(skills[0], body);
      return skills[0];
    },
    'DELETE /skills/1': () => {
      skills.splice(0, 1);
      return new Response(null, { status: 204 });
    },
    ...overrides,
  });
  renderApp(<SkillsPage />, { route: '/skills', path: '/skills' });
  return { ...api, user: userEvent.setup(), skills };
}

describe('skills page', () => {
  it('lists registered skills and shows the selected one', async () => {
    skillsSetup([SKILL_A, SKILL_B]);
    const detail = await screen.findByRole('region', { name: 'Skill step-by-step' });
    expect(within(detail).getByText(SKILL_A.instructions)).toBeInTheDocument();
    await screen.findByRole('button', { name: /concise/ });
  });

  it('creates a skill directly and selects it', async () => {
    const { user, calls } = skillsSetup([]);
    expect(await screen.findByText('No skills yet')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'New skill' }));
    await user.type(screen.getByLabelText('Name'), 'step-by-step');
    await user.type(screen.getByLabelText('Instructions (Markdown)'), 'Think step by step.');
    await user.click(screen.getByRole('button', { name: 'Create skill' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path === '/skills')).toBe(true),
    );
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({
      name: 'step-by-step',
      description: '',
      instructions: 'Think step by step.',
    });
    expect(await screen.findByRole('region', { name: 'Skill step-by-step' })).toBeInTheDocument();
  });

  it('shows a duplicate-name error from the server and creates nothing', async () => {
    const { user, skills } = skillsSetup([SKILL_A], {
      'POST /skills': () => jsonError(409, "A skill named 'step-by-step' already exists"),
    });
    await screen.findByRole('region', { name: 'Skill step-by-step' });
    await user.click(screen.getByRole('button', { name: 'New skill' }));
    await user.type(screen.getByLabelText('Name'), 'step-by-step');
    await user.type(screen.getByLabelText('Instructions (Markdown)'), 'x');
    await user.click(screen.getByRole('button', { name: 'Create skill' }));
    expect(await screen.findByText(/already exists/)).toBeInTheDocument();
    expect(skills).toHaveLength(1);
  });

  it('edits a skill’s instructions', async () => {
    const { user, calls } = skillsSetup([SKILL_A]);
    const detail = await screen.findByRole('region', { name: 'Skill step-by-step' });
    await user.click(within(detail).getByRole('button', { name: 'Edit' }));
    const textarea = screen.getByLabelText('Instructions (Markdown)');
    await user.clear(textarea);
    await user.type(textarea, 'New instructions.');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PATCH' && c.path === '/skills/1')).toBe(true),
    );
    expect(calls.find((c) => c.method === 'PATCH')!.body.instructions).toBe('New instructions.');
    expect(await screen.findByText('New instructions.')).toBeInTheDocument();
  });

  it('deletes a skill after confirmation', async () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    );
    const { user, calls, skills } = skillsSetup([SKILL_A]);
    const detail = await screen.findByRole('region', { name: 'Skill step-by-step' });
    await user.click(within(detail).getByRole('button', { name: 'Delete skill step-by-step' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path === '/skills/1')).toBe(true),
    );
    await waitFor(() => expect(skills).toHaveLength(0));
  });

  it('uploads a skill from a file picker and submits its content', async () => {
    const { user, calls } = skillsSetup([]);
    await screen.findByText('No skills yet');
    await user.click(screen.getByRole('button', { name: 'Upload…' }));
    const file = new File(
      ['step-by-step\n\nThink before answering\n\nThink step by step, then give the final answer.'],
      'step-by-step.md',
      { type: 'text/markdown' },
    );
    const input = screen.getByLabelText('File (.md)');
    await user.upload(input, file);
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path === '/skills/import')).toBe(true),
    );
    const call = calls.find((c) => c.method === 'POST' && c.path === '/skills/import')!;
    expect(call.body.content).toContain('Think step by step, then give the final answer.');
    expect(call.body.filename).toBe('step-by-step.md');
    expect(await screen.findByRole('region', { name: 'Skill step-by-step' })).toBeInTheDocument();
  });

  it('reports an invalid upload without creating anything', async () => {
    const { user, skills } = skillsSetup([], {
      'POST /skills/import': () =>
        jsonError(422, {
          code: 'invalid_skill_file',
          errors: [{ field: 'instructions', message: 'field required' }],
        }),
    });
    await screen.findByText('No skills yet');
    await user.click(screen.getByRole('button', { name: 'Upload…' }));
    const file = new File(['name only'], 'name-only.md', { type: 'text/markdown' });
    await user.upload(screen.getByLabelText('File (.md)'), file);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('nothing was created');
    expect(alert).toHaveTextContent('instructions: field required');
    expect(skills).toHaveLength(0);
  });
});
