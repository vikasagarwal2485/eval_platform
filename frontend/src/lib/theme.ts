/** Explicit light/dark override (spec `frontend-design-system`: "The user SHALL be able to
 * explicitly choose light or dark presentation... and that choice SHALL persist across visits").
 * `null` (nothing stored yet) means no explicit choice has been made - the existing
 * `prefers-color-scheme` CSS behavior applies unchanged. Plain functions, not a hook: `main.tsx`
 * calls `applyTheme(getStoredTheme())` synchronously before React ever mounts (design.md D5), so
 * there is never a flash of the OS-preferred theme before the user's own choice takes over. */

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'theme';

export function getStoredTheme(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'light' || v === 'dark' ? v : null;
  } catch {
    return null; // localStorage unavailable (private mode, blocked) - just follow the OS preference
  }
}

export function applyTheme(theme: Theme | null): void {
  if (theme) document.documentElement.setAttribute('data-theme', theme);
  else document.documentElement.removeAttribute('data-theme');
}

export function setStoredTheme(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // ignore - the choice just won't persist past this page load
  }
  applyTheme(theme);
}

export function prefersDark(): boolean {
  try {
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  } catch {
    return false;
  }
}
