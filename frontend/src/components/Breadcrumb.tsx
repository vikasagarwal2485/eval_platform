import { Link } from 'react-router-dom';

/** Spec `frontend-design-system`: "A drilled-into view shows a breadcrumb back to its list" -
 * `listLabel`/`listPath` name the list this record was selected from (e.g. "Agents"/"/agents"),
 * `current` is that specific record's own label (e.g. the agent's name). Reads straight from data
 * the calling page already has loaded (design.md D6) - never a new fetch of its own. */
export default function Breadcrumb({
  listLabel,
  listPath,
  current,
}: {
  listLabel: string;
  listPath: string;
  current: string;
}) {
  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <Link to={listPath}>{listLabel}</Link>
      {' / '}
      <span className="current">{current}</span>
    </nav>
  );
}
