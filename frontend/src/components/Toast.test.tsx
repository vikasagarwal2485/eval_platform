import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToastProvider, useToast } from './Toast';

function Harness() {
  const toast = useToast();
  return (
    <>
      <button onClick={() => toast.success('Credential rotated.')}>Rotate</button>
      <button onClick={() => toast.error('Rotation failed.')}>Fail rotate</button>
    </>
  );
}

function renderHarness() {
  return render(
    <ToastProvider>
      <div>page content</div>
      <Harness />
    </ToastProvider>,
  );
}

describe('Toast', () => {
  afterEach(() => vi.useRealTimers());

  it('shows a success toast that auto-dismisses after its timer', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByText('Rotate'));
    expect(screen.getByText('Credential rotated.')).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(4000));
    expect(screen.queryByText('Credential rotated.')).not.toBeInTheDocument();
  });

  it('shows an error toast without altering existing page content', async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByText('Fail rotate'));
    expect(screen.getByText('Rotation failed.')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Rotation failed.');
    expect(screen.getByText('page content')).toBeInTheDocument();
  });

  it('stacks multiple toasts and dismisses each independently', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByText('Rotate'));
    act(() => vi.advanceTimersByTime(2000));
    await user.click(screen.getByText('Fail rotate'));
    expect(screen.getByText('Credential rotated.')).toBeInTheDocument();
    expect(screen.getByText('Rotation failed.')).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(2000)); // first toast's 4s elapses, second's doesn't yet
    expect(screen.queryByText('Credential rotated.')).not.toBeInTheDocument();
    expect(screen.getByText('Rotation failed.')).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(2000)); // second toast's own 4s now elapses too
    expect(screen.queryByText('Rotation failed.')).not.toBeInTheDocument();
  });

  it('useToast throws when used outside a ToastProvider', () => {
    const Bare = () => {
      useToast();
      return null;
    };
    expect(() => render(<Bare />)).toThrow(/ToastProvider/);
  });
});
