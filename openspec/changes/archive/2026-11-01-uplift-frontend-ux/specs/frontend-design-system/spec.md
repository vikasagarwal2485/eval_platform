# Spec Delta

## Purpose

Defines the platform's shared, cross-cutting UI/UX conventions - visual tokens, interaction
primitives, navigation shell, and list pagination - applied uniformly across every view instead of
decided freshly per page.

## ADDED Requirements

### Requirement: A consistent visual token scale governs every view
The web UI SHALL define, and every view SHALL draw from, a single type scale, spacing scale,
neutral color scale, and elevation/overlay scale, rather than any view introducing its own
one-off sizing, spacing, or color value. Numeric values displayed in a table or metric SHALL use a
tabular (fixed-width digit) presentation.

#### Scenario: A page title is sized consistently everywhere
- **WHEN** any view renders its top-level page title
- **THEN** it uses the same type-scale step every other view's page title uses, with no
  view-specific override

#### Scenario: Spacing between cards and sections is drawn from the shared scale
- **WHEN** any view lays out cards, form fields, or sections
- **THEN** the gaps between them are one of the shared scale's defined steps, not a one-off value
  introduced for that view alone

#### Scenario: Numbers in tables and metrics align on their digits
- **WHEN** a table column or metric displays a number (a count, a score, a duration, a token
  count)
- **THEN** its digits are rendered with a fixed (tabular) width, so a column of numbers stays
  vertically aligned regardless of digit count

#### Scenario: A floating surface uses the shared elevation treatment
- **WHEN** a dialog, toast, or tooltip renders above the page's normal content
- **THEN** it uses the shared elevation (shadow) and overlay (scrim) tokens, not a view-specific
  shadow or backdrop color

### Requirement: Destructive actions are confirmed through an in-app dialog
The web UI SHALL confirm every destructive action (for example deleting a run) through an in-app
confirmation dialog consistent with the rest of the UI's visual language, rather than the browser's
native `confirm()` prompt. The dialog SHALL be dismissible via an explicit Cancel action, the Escape
key, or clicking outside it, and SHALL trap keyboard focus while open.

#### Scenario: Confirming a destructive action proceeds
- **WHEN** the user triggers a destructive action and confirms it in the dialog
- **THEN** the action proceeds exactly as it would have after a native browser confirmation, and
  the dialog closes

#### Scenario: Dismissing the dialog cancels the action
- **WHEN** the user presses Escape, clicks outside the dialog, or clicks Cancel
- **THEN** the destructive action does not proceed and the dialog closes

#### Scenario: Focus stays within the open dialog
- **WHEN** the confirmation dialog is open and the user tabs through focusable elements
- **THEN** focus never moves to an element outside the dialog until it closes

### Requirement: Mutation feedback is surfaced as a transient toast
Following a user-initiated action that succeeds or fails outside the context of a persistent,
blocking error state, the web UI SHALL surface a brief, auto-dismissing toast notification stating
the outcome, in addition to (not instead of) any existing persistent error banner used for
page-level failures.

#### Scenario: A successful action shows a success toast
- **WHEN** a user-initiated action (for example rotating a credential) completes successfully
- **THEN** a toast confirming success appears and dismisses itself automatically after a short
  delay, without requiring the user to dismiss it manually

#### Scenario: A failed action shows an error toast without replacing page content
- **WHEN** a user-initiated action fails
- **THEN** a toast stating the failure appears, and the page's own content and any existing
  persistent error banner are unaffected by the toast's appearance or dismissal

#### Scenario: Multiple toasts stack rather than replace each other
- **WHEN** a second toast is triggered while an earlier one is still visible
- **THEN** both are visible at once, stacked, each dismissing independently on its own timer

### Requirement: The header shows product identity, location, and a user-controlled theme
The web UI's header SHALL show a consistent product mark alongside the primary navigation on every
view. A view reached by drilling into a specific record (for example one agent's detail page, or
one run's results) SHALL show a breadcrumb trail back to that record's list view. The user SHALL be
able to explicitly choose light or dark presentation, overriding the operating system's own
preference, and that choice SHALL persist across visits.

#### Scenario: The product mark and primary navigation appear on every view
- **WHEN** any view is loaded
- **THEN** the header shows the product mark and the primary navigation, with the current
  top-level section indicated

#### Scenario: A drilled-into view shows a breadcrumb back to its list
- **WHEN** the user is on a view reached by selecting one specific record from a list (an agent's
  detail page, a run's results or live page)
- **THEN** a breadcrumb trail is shown naming that list and the specific record, and the list
  portion is a link back to it

#### Scenario: A top-level view shows no breadcrumb
- **WHEN** the user is on a top-level view not reached by drilling into a specific record
- **THEN** no breadcrumb trail is shown, only the page's own title

#### Scenario: An explicit theme choice overrides the operating system preference
- **WHEN** the user explicitly chooses light or dark presentation
- **THEN** the UI immediately switches to that presentation regardless of the operating system's
  own preference, and shows that same choice on the user's next visit

#### Scenario: No explicit choice yet made follows the operating system preference
- **WHEN** the user has never explicitly chosen a presentation
- **THEN** the UI follows the operating system's own light/dark preference, exactly as it does
  today

### Requirement: A list that can grow unbounded is paginated
Any view that lists records, that number can reasonably grow into the hundreds in a real
deployment (runs, agents, skills, suites), SHALL present that list a page at a time rather than
rendering every record at once, with a visible control for the current page, the total number of
records, and the number of records shown per page.

#### Scenario: A list longer than one page shows pagination controls
- **WHEN** a list has more records than the current page size
- **THEN** the view shows the current page's records, the total record count, and controls to move
  to the next or previous page

#### Scenario: A list that fits on one page shows no pagination controls
- **WHEN** a list has fewer records than the smallest page size
- **THEN** every record is shown and no pagination controls are rendered

#### Scenario: Changing the page size re-renders from the first page
- **WHEN** the user changes the selected page size while viewing a page other than the first
- **THEN** the view returns to the first page, now sized to the newly selected page size

#### Scenario: An empty list is unaffected by pagination
- **WHEN** a paginated list has no records at all
- **THEN** the view's existing empty state is shown, not an empty page of pagination controls
