import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import App from './App';
import { mockApi } from './test/utils';

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('routing', () => {
  beforeEach(() => {
    mockApi({}); // pages fetch on mount; every call 404s, which the pages handle
  });
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ['/', 'Run Evaluation setup'],
    ['/runs/1/live', 'Live run'],
    ['/runs/1', 'Results'],
    ['/suites', 'Suites'],
    ['/providers', 'Models'],
    ['/skills', 'Skills'],
    ['/agents', 'Agents'],
    ['/history', 'History'],
    ['/nope', 'Page not found'],
  ])('renders %s', (path, heading) => {
    renderAt(path);
    expect(screen.getByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
  });

  it('has a Models link in the main navigation', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: 'Models' })).toHaveAttribute('href', '/providers');
  });

  it('has an Agents link in the main navigation', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: 'Agents' })).toHaveAttribute('href', '/agents');
  });

  it('has a Skills link in the main navigation, between Models and Agents (add-agent-playground)', () => {
    renderAt('/');
    const mainNav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(mainNav).getByRole('link', { name: 'Skills' })).toHaveAttribute('href', '/skills');
    const names = within(mainNav)
      .getAllByRole('link')
      .map((el) => el.textContent);
    expect(names.indexOf('Models')).toBeLessThan(names.indexOf('Skills'));
    expect(names.indexOf('Skills')).toBeLessThan(names.indexOf('Agents'));
  });

  it('marks the active nav link', () => {
    renderAt('/suites');
    expect(screen.getByRole('link', { name: 'Suites' })).toHaveAttribute('aria-current', 'page');
  });

  it('shows the product name', () => {
    renderAt('/');
    expect(screen.getByText('Model Eval Platform')).toBeInTheDocument();
  });

  it('does not list Suites or History as separate top-level nav items', () => {
    renderAt('/');
    const mainNav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(mainNav).queryByRole('link', { name: 'Suites' })).toBeNull();
    expect(within(mainNav).queryByRole('link', { name: 'History' })).toBeNull();
  });

  it('does not list Skills as a Run Evaluation setup sub-tab (add-agent-playground: it moved to the main nav)', () => {
    renderAt('/');
    const subNav = screen.getByRole('navigation', { name: 'Run Evaluation setup sections' });
    expect(within(subNav).queryByRole('link', { name: 'Skills' })).toBeNull();
  });

  it.each(['/', '/suites', '/history'])(
    'shows Suites and History as sub-tabs under Run Evaluation setup at %s',
    (path) => {
      renderAt(path);
      const subNav = screen.getByRole('navigation', { name: 'Run Evaluation setup sections' });
      expect(within(subNav).getByRole('link', { name: 'Setup' })).toHaveAttribute('href', '/');
      expect(within(subNav).getByRole('link', { name: 'Suites' })).toHaveAttribute(
        'href',
        '/suites',
      );
      expect(within(subNav).getByRole('link', { name: 'History' })).toHaveAttribute(
        'href',
        '/history',
      );
    },
  );

  it.each(['/', '/suites', '/history'])(
    'marks "Run Evaluation setup" active in the main nav at %s',
    (path) => {
      renderAt(path);
      const mainNav = screen.getByRole('navigation', { name: 'Main' });
      expect(within(mainNav).getByRole('link', { name: 'Run Evaluation setup' })).toHaveAttribute(
        'aria-current',
        'page',
      );
    },
  );

  it('does not mark "Run Evaluation setup" active outside its own sub-tabs', () => {
    renderAt('/providers');
    const mainNav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(mainNav).getByRole('link', { name: 'Run Evaluation setup' })).not.toHaveAttribute(
      'aria-current',
    );
  });

  it('does not mark "Run Evaluation setup" active on the Skills page', () => {
    renderAt('/skills');
    const mainNav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(mainNav).getByRole('link', { name: 'Run Evaluation setup' })).not.toHaveAttribute(
      'aria-current',
    );
    expect(within(mainNav).getByRole('link', { name: 'Skills' })).toHaveAttribute('aria-current', 'page');
  });
});
