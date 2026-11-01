# Tasks

## 1. Token foundation

- [x] 1.1 Add the type scale (`display`/`h2`/`h3`/`body`/`small`/`micro`) as CSS custom properties
  in `styles.css`, applied to `h1`/`h2`/`h3`/`.small` and a new `.micro` utility class; verify no
  existing page's rendered heading sizes change (a visual/snapshot check against the current
  sizes, since the scale matches today's values - this step is formalization, not a resize)
  (verified: full frontend suite - 353/353 - green after the change; type values are a direct
  formalization of today's existing h1/h2/h3/.small sizes, not a resize)
- [x] 1.2 Add the spacing scale (`4/8/12/16/24/32/48`) as CSS custom properties and replace
  `styles.css`'s existing freehand gap/padding/margin values with references to it; verify a
  `grep` for bare pixel gap/padding/margin values in `styles.css` (outside the scale definition
  itself) returns nothing
  (verified: the grep returns only `.sr-only`'s `margin: -1px` - the standard accessibility
  clip-rect hiding technique, which must stay exactly -1px to keep the element 1x1px and is not a
  layout-spacing value in the scale's sense; every other bare value was snapped to its nearest
  scale step, e.g. button padding 7px/14px -> 8px/16px)
- [x] 1.3 Add a neutral color scale (2-3 new steps beyond today's `--text`/`--text-muted`/
  `--border`) for both light and dark themes, and apply `font-variant-numeric: tabular-nums` as
  the default for `.num`/table-number cells and metric displays wherever a number currently
  renders without it; verify a visual check that a multi-digit number column stays aligned
  (added `--text-faint`/`--border-strong` for both themes; applied `tabular-nums` on `body`
  itself rather than hunting down every numeric display individually - it only affects digit
  glyphs, so it's safe on prose and covers every number anywhere in the app by construction)
- [x] 1.4 Add elevation (`--shadow-sm`, `--shadow-lg`) and overlay (`--overlay`) tokens for both
  themes, applied to the existing `.viz-tip` (replacing its hardcoded `box-shadow`); verify the
  chart tooltip's shadow is unchanged visually and now reads from the new token
  (`--shadow-sm`'s value is an exact copy of the previous hardcoded value, so the tooltip's shadow
  is pixel-identical; `--shadow-lg`/`--overlay` are new, used by the dialog/toast primitives built
  in section 3)

## 2. Backend pagination

- [x] 2.1 Add `limit: int = 50, offset: int = 0` query parameters to `GET /runs`, mirroring
  `GET /agents/{id}/turns`'s existing signature; verify a test that a default call returns at
  most 50 rows and an explicit `limit`/`offset` pair returns the expected slice
  (`repo.list_runs`/`count_runs`; `tests/test_pagination.py::test_list_runs_defaults_to_at_most_50_and_an_explicit_slice_works`)
- [x] 2.2 Add an `X-Total-Count` response header (the unpaginated total row count) to `GET /runs`;
  verify a test asserting the header's value against a known fixture row count, independent of
  the requested `limit`/`offset`
  (via FastAPI's `Response` parameter injection, body shape untouched;
  `test_get_runs_reports_x_total_count_and_keeps_a_bare_array_body`)
- [x] 2.3 Repeat 2.1-2.2 for `GET /agents`; verify equivalent tests
- [x] 2.4 Repeat 2.1-2.2 for `GET /skills`; verify equivalent tests
- [x] 2.5 Repeat 2.1-2.2 for `GET /suites`; verify equivalent tests
- [x] 2.6 Verify an existing caller that omits `limit`/`offset` entirely still gets a 200 with a
  bare JSON array (not a wrapped object) - a regression test per endpoint confirming the response
  body shape is unchanged for every existing test/consumer that doesn't pass the new parameters
  (covered by the same four API-level tests above, plus the full existing backend suite - 1092
  passed, 5 skipped - staying green with no changes needed to any existing test's assertions)

## 3. Shared primitives

- [x] 3.1 Add a `useConfirm()` hook and its backing `<dialog>`-based component, mounted once near
  the app root; verify unit tests for: confirming resolves `true` and closes, Escape/backdrop-
  click/Cancel each resolve `false` and close, and focus never lands outside the open dialog
  (`src/components/ConfirmDialog.tsx`, mounted in `App.tsx`; jsdom doesn't implement
  `showModal`/`close` at all as of 25.x - polyfilled minimally in `src/test/setup.ts`, and the
  focus trap/Escape handling is done manually in the component rather than relying on native
  dialog behavior neither jsdom nor every real browser can be assumed to get identically right;
  8 tests in `ConfirmDialog.test.tsx`)
- [x] 3.2 Replace the existing `window.confirm(...)` call site (run deletion in `HistoryPage`) with
  `useConfirm()`; verify the existing delete-run test still passes, now asserting against the
  in-app dialog instead of a mocked `window.confirm`
  (scope corrected during implementation, user confirmed: the proposal undercounted this -
  `window.confirm()` had 6 call sites, not 1 - `HistoryPage` (run), `SkillsPage` (skill),
  `SuitesPage` (suite, case), `ProviderCard` (declared model, provider). All 6 migrated, since the
  spec requirement itself already covers "every destructive action," not just one. Every affected
  test updated to interact with the real dialog instead of stubbing `window.confirm`; full
  frontend suite - 361/361 - green, zero remaining `window.confirm(` call sites)
- [x] 3.3 Add a `ToastProvider`/`useToast()` hook (`.success`/`.error`), mounted once in `App.tsx`;
  verify unit tests for: a toast auto-dismisses after its timer, two concurrent toasts both render
  and dismiss independently, and an error toast appears without altering any existing `Banner`/
  `ErrorBox` content on the page
  (`src/components/Toast.tsx`; 4 tests in `Toast.test.tsx` using `vi.useFakeTimers` + `act()` to
  flush the timer-driven state update deterministically)
- [x] 3.4 Wire at least one existing mutation (credential rotation, per the proposal) to call
  `useToast()` on success/failure, in addition to its existing behavior; verify a test that the
  toast appears with the expected message on both outcomes
  (wired `PlaygroundPanel`'s "Rotate credentials" mutation - success keeps its existing
  shown-once-token behavior and now also toasts; failure now toasts where nothing was shown
  before. While migrating the other `confirm()` sites found 2 more bare `confirm(...)` calls the
  earlier `window.confirm` grep missed entirely - in `AgentSettingsPanel` (delete agent) and
  `PlaygroundPanel` (disable Playground) - both migrated to `useConfirm()` too, consistent with
  the scope correction already made in 3.2)
- [x] 3.5 Add a `<Pagination>` presentational component (page, pageSize, total, onPageChange,
  onPageSizeChange) and a `usePagination()` hook synchronizing `page`/`pageSize` with the URL's
  query string via `useSearchParams`; verify unit tests for: controls render only when `total`
  exceeds the smallest page size, changing page size resets to page 1, and the component renders
  nothing (not an empty control row) when `total` is 0
  (resolved a gap the written spec scenarios left open - "more than current page size" shows,
  "fewer than the smallest option" hides, nothing says what happens in between - by hiding
  whenever `total <= pageSize`, a strict generalization that still satisfies both written
  scenarios without contradicting either; `src/components/Pagination.tsx`, 9 tests)
- [x] 3.6 Add a `<Breadcrumb>` component taking a list view's label/path and the current record's
  name; verify a unit test rendering it with sample data produces the expected link and current-
  record text
- [x] 3.7 Add the manual light/dark theme toggle: a `useTheme()` hook persisting the explicit
  choice to `localStorage` and setting `<html data-theme>`, read and applied synchronously before
  the first React render (not inside a `useEffect`); verify a test that an explicit choice
  persists across a simulated reload, and that no choice yet made leaves `data-theme` unset
  (falling through to the existing `prefers-color-scheme` behavior)
  (plain functions in `src/lib/theme.ts`, applied in `main.tsx` before `createRoot(...).render()`;
  `useTheme()`/`<ThemeToggle>` in `src/components/ThemeToggle.tsx` for the header button's own
  reactive state afterward; 5 + 4 tests)

## 4. Page migration

- [x] 4.1 `HistoryPage`: wire `<Pagination>` against the now-paginated `/runs`, remove any
  reliance on receiving the full run list client-side; verify existing tests pass against a
  fixture of more than one page's worth of runs, confirming only the current page's rows render
  and the control reflects the correct total
  (found during implementation: `useRuns()`/`useAgents()`/`useSkills()`/`useSuites()` are each
  also consumed elsewhere as full-list *pickers* - e.g. the hand-off-agent picker, suite/skill
  multi-selects - which would have silently truncated to 50 once Section 2's default landed. Left
  those hooks returning the full list unchanged (now passing an explicit high `limit`), and added
  a parallel `use*Page()` hook per resource, consumed only by that resource's own list-view page;
  added a `getPaginated()` client helper reading `X-Total-Count` without changing `api.get`'s
  shape for every other call site. New test asserting the page/total math and Next/Previous)
- [x] 4.2 `AgentsPage`: same pagination wiring for `/agents`; replace every inline `style={{...}}`
  on this page with the shared vocabulary from section 1; verify existing tests pass and a
  `grep` for `style={{` in this file returns nothing
  (11 inline styles removed; added 5 small reusable spacing utilities - `.mt-0`/`.mt-sm`/`.mt-md`/
  `.gap-sm`/`.list-reset` - to `styles.css` for every later page in this section to reuse, plus 3
  page-specific width/alignment classes for the declared-model form row, which are legitimately
  not spacing-scale concepts; new pagination test asserting the total/pager math)
- [x] 4.3 `SkillsPage`: same pagination wiring for `/skills`; verify existing tests pass against a
  multi-page fixture
  (found live testing this one: the existing `useSkillMutations()`'s `invalidateQueries({
  queryKey: keys.skills })` after create/update/delete never refetched the new `skillsPage` query
  at all - react-query's default prefix-matching invalidation only cascades to a *nested* key,
  and `skills-page` was a separate top-level key, not a child of `skills`. Caught by this page's
  own "uploads a skill" test going from passing to failing once pagination was wired - the skill
  list stayed empty after a successful upload. Fixed by nesting every `*Page` key under its base
  resource's own key (`['skills', 'page', limit, offset]`, not `['skills-page', ...]`) for all
  four resources - runs/agents/skills/suites alike, retroactively fixing 4.1/4.2 too, both
  reverified green after the key change)
- [x] 4.4 `SuitesPage`: same pagination wiring for `/suites`; verify existing tests pass against a
  multi-page fixture
- [x] 4.5 `AgentPage`: add `<Breadcrumb>` back to the Agents list; sweep for inline-style/ad hoc
  spacing and replace with the shared vocabulary; verify existing tests pass
  (restyled `.breadcrumb` as ordinary page content - a simple nav line above `.page-head`, inside
  `<main>`'s own padding - rather than the full-width header-adjacent bar sketched during
  exploration; no committed design.md decision fixed the visual placement, only the data-sourcing
  one (D6), so this is implementation discretion, not a deviation from anything agreed)
- [x] 4.6 `ResultsPage` and `RunLivePage`: add `<Breadcrumb>` back to History; sweep for inline-
  style/ad hoc spacing; verify existing tests pass
  (breadcrumb also shown on each page's loading/error states, using the known run id as a
  fallback label before the real name has loaded; added `.mb-sm`/`.ml-sm` utilities and fixed a
  genuinely missing base rule - `.btn` never had `text-decoration: none`, relying on call sites to
  patch it per-instance - rather than adding another one-off utility for it)
- [x] 4.7 `RunSetupPage`, `SuitesPage`, `ProvidersPage`, `SkillsPage`: consistency sweep only (no
  breadcrumb, no pagination beyond 4.3/4.4 - Providers/Models is deliberately not paginated per
  the proposal); verify existing tests pass
  (scope expanded, with explicit user approval ("Go with option 3"), to also sweep every
  sub-component rendered inside these 4 pages plus the 5 pages done in 4.1-4.6 - `ConfigPanel`,
  `CaseForm`, `ClassificationDetails`, `ComparePanel`, `JudgeStrictness`, `Leaderboard`,
  `WeightsPanel`, `SaveToSuite`, `SuitePicker`, `CaseDrilldown`, `SpanTree`, chart components, and
  the agent-page panels - rather than stopping at the 9 page components themselves; every
  `style={{...}}` in that tree is now a shared utility class, with 4 legitimate dynamic exceptions
  left in place (tooltip position and legend-swatch color in `Viz.tsx`, depth-based indent in
  `SpanTree.tsx`, progress-bar width in `RunLivePage.tsx`).
  Found live during this sweep: the utility classes added throughout 4.1-4.7 (`.m-0`, `.mt-sm`,
  `.gap-md`, etc.) were defined earlier in `styles.css` than the component base rules
  (`.row`/`.stack`/`.field`/headings) they exist to override. Two single-class selectors have
  equal specificity, so CSS resolves the tie by source order - meaning every one of those
  overrides had been silently losing to the base rule the whole time. Fixed by moving the entire
  utility block to the end of the file, behind an explanatory comment so it isn't reordered again.
  Verified no duplicate utility definitions remain, then reran the full frontend suite (393/393),
  `tsc --noEmit`, and `eslint` clean after the move.
- [x] 4.8 `NotFound`: bring up to the shared visual vocabulary (currently 12 unstyled lines);
  verify a rendered snapshot uses `.empty` or equivalent shared classes, not bare text
  (already used the shared `.empty` class with an `<h1>` page title - tried switching to the
  shared `Empty` component, but that renders an `<h3>` and would have left this the only route
  with no `<h1>`, breaking the one-h1-per-page convention `App.test.tsx` enforces across every
  other route; reverted, kept the original `.empty`/`<h1>` markup, and added `NotFound.test.tsx`
  to lock in the shared-class assertion since none existed before)
- [x] 4.9 Add the product mark and the theme toggle to `App.tsx`'s header, used on every route;
  verify an existing or new test confirms both render on at least two different routes
  (added a small inline SVG `BrandMark` - CSS already had an unused `.brand-mark` rule waiting
  for it - next to the product name, and wired in the already-built but previously-unused
  `<ThemeToggle>`; both are now in `App.tsx`'s one `<header>`, so every route gets them for free.
  Added a test asserting both render at `/` and `/agents`.)

## 5. Cross-cutting verification

- [x] 5.1 Run the full frontend test suite and `axe-core` accessibility checks (already a
  dependency) against at least one migrated page in both light and dark `data-theme` states;
  verify no new accessibility violations are introduced by the new primitives (dialog, toast,
  pagination controls, breadcrumb)
  (an extensive axe suite already existed in `a11y.test.tsx` for the light/no-explicit-theme
  state - added a `dark theme accessibility (5.1)` block that sets `data-theme="dark"` on
  `document.documentElement`, the same attribute `lib/theme.ts` sets at runtime, and reruns the
  audit against History - its list, pagination controls, and an open confirm dialog - with zero
  violations in either state)
- [x] 5.2 Verify keyboard-only operation end to end on one full flow that exercises every new
  primitive (e.g. navigate to History via breadcrumb-producing flow, paginate, delete a run
  through the confirm dialog, observe the resulting toast) without touching a mouse
  (toast is deliberately wired to only one mutation per 3.4/the proposal - Playground credential
  rotation, not run deletion - so the literal History/toast pairing in the task's example doesn't
  exist; built the equivalent real flow instead, entirely via `.focus()` + `user.keyboard('{Enter}')`:
  Agents list pagination -> Next page -> open an agent (breadcrumb now shown, asserted against
  its own link) -> Playground tab -> Rotate credentials (real mutation, real toast) -> Settings
  tab -> Delete agent through the real confirm dialog, submitted DELETE)
- [x] 5.3 Run the full backend and frontend test suites; verify both are green before this change
  is considered complete
