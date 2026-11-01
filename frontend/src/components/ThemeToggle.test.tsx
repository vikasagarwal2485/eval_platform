import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ThemeToggle from './ThemeToggle';

describe('ThemeToggle', () => {
  afterEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it('leaves data-theme unset when no explicit choice has been made', () => {
    render(<ThemeToggle />);
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('clicking sets an explicit choice, reflected on <html data-theme>', async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    await user.click(screen.getByRole('button'));
    // jsdom has no matchMedia, so prefersDark() is false -> the first toggle goes to dark
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('toggling again switches back', async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    await user.click(screen.getByRole('button'));
    await user.click(screen.getByRole('button'));
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('an explicit choice persists across a simulated reload', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<ThemeToggle />);
    await user.click(screen.getByRole('button')); // -> dark
    unmount();
    document.documentElement.removeAttribute('data-theme'); // simulate a fresh page load's blank slate

    render(<ThemeToggle />); // a fresh mount, as a reload would be
    expect(screen.getByRole('button')).toHaveAccessibleName('Switch to light theme'); // still reads as dark
  });
});
