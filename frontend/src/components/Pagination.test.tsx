import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import Pagination, { usePagination } from './Pagination';

describe('Pagination (presentational)', () => {
  it('renders nothing when every record already fits on the current page', () => {
    render(
      <Pagination page={1} pageSize={50} total={30} onPageChange={vi.fn()} onPageSizeChange={vi.fn()} />,
    );
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  it('renders nothing for an empty list, not an empty row of controls', () => {
    render(
      <Pagination page={1} pageSize={50} total={0} onPageChange={vi.fn()} onPageSizeChange={vi.fn()} />,
    );
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  it('shows controls and the current range when the list exceeds the current page size', () => {
    render(
      <Pagination page={1} pageSize={50} total={120} onPageChange={vi.fn()} onPageSizeChange={vi.fn()} />,
    );
    expect(screen.getByText('Showing 1-50 of 120')).toBeInTheDocument();
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
  });

  it('disables Previous on the first page and Next on the last page', () => {
    render(
      <Pagination page={3} pageSize={50} total={120} onPageChange={vi.fn()} onPageSizeChange={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: 'Previous' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(screen.getByText('Showing 101-120 of 120')).toBeInTheDocument();
  });

  it('calls onPageChange/onPageSizeChange on interaction', async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    const onPageSizeChange = vi.fn();
    render(
      <Pagination page={2} pageSize={25} total={100} onPageChange={onPageChange} onPageSizeChange={onPageSizeChange} />,
    );
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(onPageChange).toHaveBeenCalledWith(3);
    await user.click(screen.getByRole('button', { name: 'Previous' }));
    expect(onPageChange).toHaveBeenCalledWith(1);
    await user.selectOptions(screen.getByLabelText('Per page'), '100');
    expect(onPageSizeChange).toHaveBeenCalledWith(100);
  });
});

function HookHarness() {
  const { page, pageSize, setPage, setPageSize } = usePagination();
  return (
    <div>
      <span data-testid="page">{page}</span>
      <span data-testid="pageSize">{pageSize}</span>
      <button onClick={() => setPage(2)}>go to page 2</button>
      <button onClick={() => setPageSize(100)}>set page size 100</button>
    </div>
  );
}

describe('usePagination', () => {
  it('defaults to page 1 and the given default page size with no query params', () => {
    render(
      <MemoryRouter initialEntries={['/history']}>
        <HookHarness />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('page')).toHaveTextContent('1');
    expect(screen.getByTestId('pageSize')).toHaveTextContent('50');
  });

  it('reads page/pageSize from the URL when present', () => {
    render(
      <MemoryRouter initialEntries={['/history?page=3&pageSize=100']}>
        <HookHarness />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('page')).toHaveTextContent('3');
    expect(screen.getByTestId('pageSize')).toHaveTextContent('100');
  });

  it('changing page size resets to page 1', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/history?page=3']}>
        <HookHarness />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('page')).toHaveTextContent('3');
    await user.click(screen.getByText('set page size 100'));
    expect(screen.getByTestId('page')).toHaveTextContent('1');
    expect(screen.getByTestId('pageSize')).toHaveTextContent('100');
  });

  it('an invalid pageSize in the URL falls back to the default rather than being trusted', () => {
    render(
      <MemoryRouter initialEntries={['/history?pageSize=9999']}>
        <HookHarness />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('pageSize')).toHaveTextContent('50');
  });
});
