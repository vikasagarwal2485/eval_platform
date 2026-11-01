import { applyTheme, getStoredTheme, prefersDark, setStoredTheme } from './theme';

describe('theme', () => {
  afterEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it('getStoredTheme returns null when nothing has been stored yet', () => {
    expect(getStoredTheme()).toBeNull();
  });

  it('setStoredTheme persists and applies the choice; getStoredTheme reads it back', () => {
    setStoredTheme('dark');
    expect(localStorage.getItem('theme')).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(getStoredTheme()).toBe('dark');
  });

  it('applyTheme(null) removes the attribute, falling back to the OS preference', () => {
    setStoredTheme('light');
    applyTheme(null);
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('getStoredTheme ignores a garbage stored value rather than trusting it', () => {
    localStorage.setItem('theme', 'purple');
    expect(getStoredTheme()).toBeNull();
  });

  it('prefersDark never throws when matchMedia is unavailable (jsdom has none)', () => {
    expect(prefersDark()).toBe(false);
  });
});
