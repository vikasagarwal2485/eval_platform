import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfirmProvider, useConfirm } from './ConfirmDialog';

function Harness({ onResult }: { onResult: (v: boolean) => void }) {
  const confirm = useConfirm();
  return (
    <button onClick={() => confirm({ title: 'Delete run', body: 'This cannot be undone.' }).then(onResult)}>
      Delete
    </button>
  );
}

function renderHarness() {
  const onResult = vi.fn();
  render(
    <ConfirmProvider>
      <Harness onResult={onResult} />
    </ConfirmProvider>,
  );
  return { onResult };
}

describe('ConfirmDialog', () => {
  it('shows the title and body once triggered', async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByText('Delete'));
    expect(screen.getByText('Delete run')).toBeInTheDocument();
    expect(screen.getByText('This cannot be undone.')).toBeInTheDocument();
  });

  it('confirming resolves true and closes the dialog', async () => {
    const user = userEvent.setup();
    const { onResult } = renderHarness();
    await user.click(screen.getByText('Delete'));
    await user.click(screen.getByText('Confirm'));
    expect(onResult).toHaveBeenCalledWith(true);
    expect(screen.queryByText('Delete run')).not.toBeInTheDocument();
  });

  it('clicking Cancel resolves false and closes the dialog', async () => {
    const user = userEvent.setup();
    const { onResult } = renderHarness();
    await user.click(screen.getByText('Delete'));
    await user.click(screen.getByText('Cancel'));
    expect(onResult).toHaveBeenCalledWith(false);
    expect(screen.queryByText('Delete run')).not.toBeInTheDocument();
  });

  it('pressing Escape resolves false and closes the dialog', async () => {
    const user = userEvent.setup();
    const { onResult } = renderHarness();
    await user.click(screen.getByText('Delete'));
    await user.keyboard('{Escape}');
    expect(onResult).toHaveBeenCalledWith(false);
    expect(screen.queryByText('Delete run')).not.toBeInTheDocument();
  });

  it('clicking the backdrop (the dialog element itself, outside its content) resolves false', async () => {
    const user = userEvent.setup();
    const { onResult } = renderHarness();
    await user.click(screen.getByText('Delete'));
    const dialog = document.querySelector('dialog');
    await user.click(dialog!);
    expect(onResult).toHaveBeenCalledWith(false);
  });

  it('focus starts on Cancel, not the possibly-destructive Confirm action', async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByText('Delete'));
    expect(screen.getByText('Cancel')).toHaveFocus();
  });

  it('Tab never moves focus outside the open dialog', async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByText('Delete'));
    expect(screen.getByText('Cancel')).toHaveFocus();
    await user.tab();
    expect(screen.getByText('Confirm')).toHaveFocus();
    await user.tab(); // wraps back to the first focusable (Cancel), never escaping to the trigger button
    expect(screen.getByText('Cancel')).toHaveFocus();
    await user.tab({ shift: true }); // shift+tab from the first wraps to the last
    expect(screen.getByText('Confirm')).toHaveFocus();
  });

  it('useConfirm throws when used outside a ConfirmProvider', () => {
    const Bare = () => {
      useConfirm();
      return null;
    };
    expect(() => render(<Bare />)).toThrow(/ConfirmProvider/);
  });
});
