import { useSearchParams } from 'react-router-dom';

export const PAGE_SIZE_OPTIONS = [25, 50, 100];
const DEFAULT_PAGE_SIZE = 50;

/**
 * Keeps `page`/`pageSize` in the URL's query string (design.md D2) - bookmarkable/shareable, and
 * survives a refresh or a back-navigation, the same way `/runs/:id` etc. already treat the URL as
 * the source of truth for "which record". `offset`/`limit` are the matching values to pass
 * straight through to a paginated list endpoint.
 */
export function usePagination(defaultPageSize: number = DEFAULT_PAGE_SIZE) {
  const [params, setParams] = useSearchParams();

  const pageParam = Number(params.get('page'));
  const page = Number.isInteger(pageParam) && pageParam > 0 ? pageParam : 1;

  const sizeParam = Number(params.get('pageSize'));
  const pageSize = PAGE_SIZE_OPTIONS.includes(sizeParam) ? sizeParam : defaultPageSize;

  const setPage = (next: number) => {
    const p = new URLSearchParams(params);
    p.set('page', String(next));
    setParams(p, { replace: true });
  };

  const setPageSize = (next: number) => {
    const p = new URLSearchParams(params);
    p.set('pageSize', String(next));
    p.set('page', '1'); // a changed page size always returns to the first page
    setParams(p, { replace: true });
  };

  return { page, pageSize, setPage, setPageSize, offset: (page - 1) * pageSize, limit: pageSize };
}

export interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  pageSizeOptions?: number[];
}

/** Spec `frontend-design-system`: "A list that can grow unbounded is paginated" - page-based
 * controls (Prev/Next + a page-size selector), rendering nothing at all once every record
 * already fits on the current page (including an empty list - a paginated view's own empty
 * state, not an empty row of controls, is what should show there instead). */
export default function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = PAGE_SIZE_OPTIONS,
}: PaginationProps) {
  if (total <= pageSize) return null;

  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="pagination-count">
        Showing {start}-{end} of {total}
      </span>
      <div className="pagination-controls">
        <button type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          Previous
        </button>
        <span className="page-label">
          Page {page} of {lastPage}
        </span>
        <button type="button" disabled={page >= lastPage} onClick={() => onPageChange(page + 1)}>
          Next
        </button>
        <label className="pagination-size">
          Per page
          <select value={pageSize} onChange={(e) => onPageSizeChange(Number(e.target.value))}>
            {pageSizeOptions.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
      </div>
    </nav>
  );
}
