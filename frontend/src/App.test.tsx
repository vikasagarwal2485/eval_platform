import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
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
    ['/', 'Run setup'],
    ['/runs/1/live', 'Live run'],
    ['/runs/1', 'Results'],
    ['/suites', 'Suites'],
    ['/providers', 'Providers'],
    ['/agents', 'Agents'],
    ['/history', 'History'],
    ['/nope', 'Page not found'],
  ])('renders %s', (path, heading) => {
    renderAt(path);
    expect(screen.getByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
  });

  it('has a Providers link in the main navigation', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: 'Providers' })).toHaveAttribute('href', '/providers');
  });

  it('has an Agents link in the main navigation', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: 'Agents' })).toHaveAttribute('href', '/agents');
  });

  it('marks the active nav link', () => {
    renderAt('/suites');
    expect(screen.getByRole('link', { name: 'Suites' })).toHaveAttribute('aria-current', 'page');
  });
});
