# Proposal

## Why

The web UI is functionally complete but visually and interactionally unfinished: no enforced
type/spacing/color scale (inline style overrides sit next to shared CSS classes), native
`window.confirm()` for destructive actions, no transient-feedback pattern, a header that gives no
sense of place in nested views, and no pagination on lists (Run History, Agents, Skills, Suites)
that a real deployment already grows into the hundreds of rows on, even though the one list
endpoint that already paginates (`/agents/{id}/turns`) shows the pattern to extend. Shipping this
as a beta product needs it to read as deliberate, not assembled piecemeal one feature at a time.

## What Changes

- Formalize the existing CSS-variable token system into a real scale - type (6 steps), spacing (7
  steps), a neutral color scale (today only `--text`/`--text-muted`/`--border` exist), and new
  elevation/overlay tokens for floating surfaces (dialog, toast) that nothing in the app currently
  needs
- Replace ad hoc inline styling (e.g. `style={{ margin: 0, fontSize: '1.05rem' }}` next to
  `className="card-head"` in `AgentsPage.tsx`) with the shared card/badge/table/button/tabs
  vocabulary, applied consistently across all 9 pages
- Add a confirmation dialog primitive built on the native `<dialog>` element (focus trap/Esc/backdrop
  for free, no new dependency), replacing every `window.confirm()` use (run delete today; any
  future destructive action)
- Add a toast/snackbar primitive for transient mutation feedback, alongside the existing inline
  `Banner` pattern (which stays for persistent/blocking errors)
- Add a manual light/dark theme toggle in the header - the `[data-theme]` CSS override already
  exists (used today only by the chart-tooltip token block) and is otherwise unreachable by a user
- Add a small product mark and a breadcrumb row to nested views (Agent detail, Run results/live)
  for orientation
- Add page-based pagination (Prev/Next + a page-size selector) to the Run History, Agents, Skills,
  and Suites list views - each currently renders its *entire* table/grid with no limit; of these,
  `/runs`, `/agents`, `/suites` and `/skills` all need a new `limit`/`offset` query parameter added
  to match the shape `/agents/{id}/turns` already uses (Models/Providers is excluded - a curated,
  small list, not expected to reach this scale)

No new frontend dependency and no component-library adoption - every addition above builds on the
plain-CSS token system and native browser primitives already in place.

## Capabilities

### New Capabilities
- `frontend-design-system`: the platform's shared, cross-cutting UI/UX conventions - design
  tokens, the enforced component vocabulary, confirmation/toast interaction primitives, the header
  shell (branding, breadcrumbs, theme toggle), and list pagination - applied uniformly across every
  view rather than decided freshly per page

### Modified Capabilities
(none - no existing capability currently specifies any UI-level behavior for the views this change
touches; `results-dashboard` covers the Run Setup/Results/History *data* behavior, not its visual
or pagination treatment, and is unaffected by this change's own requirements)

## Impact

- **Frontend**: `src/styles.css` (token additions), `src/components/ui.tsx` and new files for
  `Dialog`/`ConfirmDialog`/`Toast`/`Pagination` primitives, `src/App.tsx` (header mark, theme
  toggle, breadcrumb wiring), every page in `src/pages/` (consistency pass + pagination on four of
  them), `src/components/agents/` (same consistency pass)
- **Backend**: `limit`/`offset` query parameters added to `GET /runs`, `GET /agents`, `GET
  /suites`, `GET /skills` (mirroring the existing `GET /agents/{id}/turns` pattern); response shape
  gains a total count for the pager to render against
- **No new dependencies**: dialog uses the native `<dialog>` element; toast is a small custom
  stack; pagination and theming are plain React state + the existing CSS token system
