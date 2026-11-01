# Design

## Context

The frontend is plain React + `react-router-dom` + `@tanstack/react-query`, zero UI dependencies,
styled entirely through one `src/styles.css` using CSS custom properties (`--bg`, `--surface`,
`--text`, `--accent`, `--good`/`--bad`/`--warn`, each with a dark-mode override under
`prefers-color-scheme`). Shared primitives already exist in `src/components/ui.tsx` (`Spinner`,
`Banner`, `ErrorBox`, `Empty`, `StatusBadge`) and a handful of CSS classes (`.card`, `.badge`,
`.table-wrap`, `.tabs`, `.progress`). See proposal.md - Why for what's inconsistent today.

The four list endpoints this change paginates already order deterministically at the database
level (`Run.id.desc()`, `Agent.name`, `Skill.name`, `Suite.is_builtin.desc(), Suite.name`) and
return a bare JSON array with no count. The one endpoint that already paginates,
`GET /agents/{id}/turns`, takes `limit: int = 50, offset: int = 0` and is consumed as an
infinite-scroll feed (more pages are fetched when the last page returned a full `limit` rows) -
it never needed a total count, which page-based pagination does.

## Goals / Non-Goals

**Goals:**
- Finish and enforce one token system (type/spacing/neutral-color/elevation) across all 9 views
- Add confirmation-dialog, toast, breadcrumb, theme-toggle, and pagination as shared primitives,
  each used identically everywhere it applies - not one-off per page
- Keep the zero-new-frontend-dependency constraint from the proposal

**Non-Goals:**
- Server-side sorting. None of the four newly-paginated lists (Runs, Agents, Skills, Suites) has
  any column sorting today, client-side or otherwise - pagination introduces no sort/pagination
  interaction to resolve, since there's nothing to resolve it with
- Redesigning the Models/Providers view's own content, or any page's actual data/metrics - this is
  a visual/interaction-consistency and scale-handling change, not a feature or information-model
  change
- A component library or CSS framework (per the proposal; this isn't revisited here)
- Mobile/phone layouts - "common desktop and laptop widths" (the existing `results-dashboard`
  usability requirement) remains the target; this change doesn't widen or narrow it

## Decisions

### D1: Pagination is `limit`/`offset` + an `X-Total-Count` response header, not a wrapped body
Extends the existing `GET /agents/{id}/turns` convention (`limit: int = 50, offset: int = 0`) to
`GET /runs`, `GET /agents`, `GET /skills`, `GET /suites`. The response body stays the bare JSON
array every existing caller (frontend hooks, backend tests) already expects; the total record
count (needed for "page N of M" and a disabled Next at the end) rides on a new `X-Total-Count`
response header instead.

Alternative considered: wrap the body as `{"items": [...], "total": N}`. Rejected - it's a
breaking shape change to four endpoints' response bodies for every existing consumer (every
backend test asserting a bare list, the frontend's own `useRuns`/`useAgents`/`useSkills`/
`useSuites` hooks) purely to carry one integer that a header carries just as well without touching
the body at all.

Omitting `limit` defaults to 50 (matching `/agents/{id}/turns`'s own default) - a caller that
relied on the old unbounded response now gets the first 50 rows unless it passes an explicit
higher `limit`. This is the intended behavior (an unbounded query is exactly what this change
removes), but it's a real behavior change for any caller besides the frontend itself - called out
again in Risks/Trade-offs and Migration Plan.

### D2: Pagination state lives in the URL, not component state
`?page=2&pageSize=50` via `useSearchParams` (already a `react-router-dom` import, no new
dependency) rather than a local `useState`. Makes a specific page bookmarkable/shareable and
survives a refresh or a back-navigation, consistent with how `/runs/:id` etc. already use the URL
as the source of truth for "which record".

### D3: The confirmation dialog is a `useConfirm()` hook over the native `<dialog>` element
A hook, not a controlled `<ConfirmDialog open={...}>` component repeated at every call site:

```
const confirm = useConfirm();
// ...
if (await confirm({ title: 'Delete run', body: '…' })) { remove.mutate(r.id); }
```

This is close to a one-line change at every existing `window.confirm(...)` call site (today:
`if (window.confirm(...)) { ... }`; after: `if (await confirm(...)) { ... }`), rather than lifting
open/confirm/cancel state into every page that has a destructive action. The dialog itself renders
once, mounted near the app root the way `ErrorBoundary` already wraps `<Routes>`, and uses the
native `<dialog>` element's own `showModal()`/`close()`, `::backdrop`, and built-in focus trap -
styled with the shared token set rather than reimplemented.

Alternative considered: a per-page `<ConfirmDialog>` with local open-state. Rejected - more
boilerplate at every call site for no behavioral difference, and the native `<dialog>`'s
focus-trap/Esc/backdrop behavior is identical either way.

### D4: Toasts are a single `ToastProvider` + `useToast()` hook, not a new per-page pattern
One stack, fixed-position (CSS `position: fixed`, no portal needed - fixed positioning escapes
normal layout regardless of DOM nesting), mounted once in `App.tsx`. `useToast().success(msg)` /
`.error(msg)` from anywhere. Existing persistent `Banner`/`ErrorBox` usage is untouched - toasts
are for one-off mutation feedback (rotate a credential, delete a run), banners stay for
page-level/blocking failures (a failed data fetch).

### D5: Theme choice is read and applied before first paint, to avoid a flash of the wrong theme
The explicit choice persists to `localStorage` and sets `<html data-theme="...">` (the CSS already
keys off `:root[data-theme='dark']`/`:not([data-theme='light'])` - today only exercised by the
chart-tooltip token block, now driven by this toggle for the whole app). Reading it and setting
the attribute happens synchronously before React mounts (a small inline step in `main.tsx`, before
`createRoot(...).render(...)`), not inside a `useEffect` after the first render - an effect-based
approach would paint the OS-preferred theme first and then flash to the user's actual choice.

### D6: Breadcrumbs are computed from already-loaded data, not a new fetch
`AgentPage` already has `agent.name` loaded before it renders its content; `ResultsPage`/
`RunLivePage` already have the run's own name/id. The breadcrumb reads straight from that existing
data - no new query, no risk of the breadcrumb's record name lagging behind the page's own title.

## Risks / Trade-offs

- **[Risk]** Defaulting `limit=50` server-side (D1) changes existing behavior for any caller that
  doesn't pass `limit` and relied on getting everything.
  → **Mitigation**: the frontend (this change's only real consumer) always passes `limit`
  explicitly once updated; any other caller that genuinely needs "all rows" can still pass a large
  explicit `limit` - nothing is made impossible, only no-longer-silently-unbounded.
- **[Risk]** `X-Total-Count` is easy to forget to read case-insensitively or to omit from a CORS
  `Access-Control-Expose-Headers` allow-list in some future deployment, silently breaking the
  pager's total/last-page display while the data itself still loads fine.
  → **Mitigation**: this app has no cross-origin frontend/backend split today (same-origin), so
  this only matters if that changes later - noted here so it isn't rediscovered the hard way.
- **[Trade-off]** The native `<dialog>` element's styling is more constrained than a hand-rolled
  overlay div (e.g. animating its `::backdrop` has less cross-browser consistency than animating a
  plain div's opacity). Accepted - the consistency and zero-dependency win outweighs a perfectly
  smooth open/close transition, and the actual browsers this app targets (recent Chrome/Firefox/
  Safari, per "common desktop and laptop widths") support `<dialog>` and `::backdrop` fully.

## Migration Plan

1. Land the token/CSS additions first (type, spacing, neutral, elevation scales) - purely
   additive, nothing visually changes until call sites adopt them.
2. Add `limit`/`offset`/`X-Total-Count` to the four list endpoints, defaulting `limit=50` - a
   behavioral change (see Risk above) but backend-only and reversible by reverting the default.
3. Build the shared primitives (`useConfirm`, `ToastProvider`/`useToast`, `<Pagination>`,
   `<Breadcrumb>`, theme toggle) against the new tokens, independent of any page adopting them yet.
4. Migrate pages one at a time: replace inline-style escapes with the shared vocabulary, swap
   `window.confirm()` call sites to `useConfirm()`, wire the four list pages to `<Pagination>`, add
   `<Breadcrumb>` to the three drilled-into views.
5. Rollback at any step: steps 1 and 3 are purely additive (nothing depends on them until step 4);
   step 2's default can be reverted independently of the frontend; step 4 is per-page, so a
   problem on one page doesn't block shipping the rest.
