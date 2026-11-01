import { useCallback, useState } from 'react';
import { getStoredTheme, prefersDark, setStoredTheme, type Theme } from '../lib/theme';

/** The current explicit theme choice (`null` = none made yet - the OS preference applies) and a
 * setter that persists it and applies it immediately. `main.tsx` already applied whatever was
 * stored before React mounted (design.md D5); this hook is for reactive UI afterward, such as
 * this toggle button's own icon/label. */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme | null>(() => getStoredTheme());

  const setTheme = useCallback((next: Theme) => {
    setStoredTheme(next);
    setThemeState(next);
  }, []);

  const toggle = useCallback(() => {
    const effectivelyDark = theme === 'dark' || (theme === null && prefersDark());
    setTheme(effectivelyDark ? 'light' : 'dark');
  }, [theme, setTheme]);

  return { theme, setTheme, toggle };
}

function SunIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="3.5" stroke="currentColor" strokeWidth="1.3" />
      <g stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
        <path d="M8 0.8v2M8 13.2v2M1.5 8h2M12.5 8h2" />
        <path d="M3.3 3.3l1.4 1.4M11.3 11.3l1.4 1.4M3.3 12.7l1.4-1.4M11.3 4.7l1.4-1.4" />
      </g>
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M13.5 9.7A5.8 5.8 0 0 1 6.3 2.5a5.8 5.8 0 1 0 7.2 7.2z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Spec `frontend-design-system`: lets the user explicitly choose light or dark, overriding the
 * OS preference. Shown in the header on every view. */
export default function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const effectivelyDark = theme === 'dark' || (theme === null && prefersDark());
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={effectivelyDark ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      {effectivelyDark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}
