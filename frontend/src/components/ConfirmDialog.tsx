import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from 'react';

export interface ConfirmOptions {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Styles the confirm action as destructive (red) - set for anything that deletes or discards data. */
  danger?: boolean;
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm | null>(null);

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Mounted once near the app root (spec `frontend-design-system`: "Destructive actions are
 * confirmed through an in-app dialog"). Renders a single native `<dialog>` reused for every call -
 * `useConfirm()` resolves once the user confirms or cancels, close to a drop-in replacement for
 * `window.confirm(...)` at each call site (design.md D3).
 */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const resolverRef = useRef<((value: boolean) => void) | null>(null);
  const [options, setOptions] = useState<ConfirmOptions | null>(null);

  const confirm = useCallback<Confirm>((opts) => {
    setOptions(opts);
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
    });
  }, []);

  useEffect(() => {
    if (options) dialogRef.current?.showModal();
  }, [options]);

  // Focus starts on Cancel, not the (possibly destructive) Confirm action, so an accidental
  // Enter press after opening never confirms by itself.
  useEffect(() => {
    if (options) cancelRef.current?.focus();
  }, [options]);

  const settle = (value: boolean) => {
    const resolve = resolverRef.current;
    resolverRef.current = null;
    resolve?.(value);
    dialogRef.current?.close();
    setOptions(null);
  };

  // A manual focus trap and Escape handler, not a reliance on the native <dialog>'s own ones -
  // jsdom doesn't model native focus-trapping or auto-fire `cancel` on Escape at all, so handling
  // both explicitly here keeps the behavior both real (harmlessly redundant with a real browser's
  // own handling) and directly testable.
  const onKeyDown = (e: KeyboardEvent<HTMLDialogElement>) => {
    if (e.key === 'Escape') {
      settle(false);
      return;
    }
    if (e.key !== 'Tab' || !dialogRef.current) return;
    const focusables = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const onBackdropClick = (e: MouseEvent<HTMLDialogElement>) => {
    if (e.target === dialogRef.current) settle(false);
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <dialog
        ref={dialogRef}
        className="modal"
        aria-labelledby="confirm-dialog-title"
        onKeyDown={onKeyDown}
        onClick={onBackdropClick}
        onCancel={(e) => {
          e.preventDefault(); // we close explicitly via settle(), not the dialog's own default
          settle(false);
        }}
      >
        {options && (
          <>
            <h2 id="confirm-dialog-title">{options.title}</h2>
            {options.body && <div className="modal-body">{options.body}</div>}
            <div className="modal-actions">
              <button ref={cancelRef} type="button" onClick={() => settle(false)}>
                {options.cancelLabel ?? 'Cancel'}
              </button>
              <button
                type="button"
                className={options.danger ? 'danger' : 'primary'}
                onClick={() => settle(true)}
              >
                {options.confirmLabel ?? 'Confirm'}
              </button>
            </div>
          </>
        )}
      </dialog>
    </ConfirmContext.Provider>
  );
}

/** Returns a function to await a confirmation, e.g. `if (await confirm({ title: '...' })) { ... }` -
 * close to a one-line swap at a `window.confirm(...)` call site (design.md D3). */
export function useConfirm(): Confirm {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error('useConfirm must be used within a ConfirmProvider');
  return ctx;
}
