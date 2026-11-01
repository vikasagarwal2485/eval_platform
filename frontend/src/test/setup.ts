import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => cleanup());

// jsdom's File/Blob don't implement `.text()` (used by file-picker upload controls, e.g.
// SkillsPage/SuitesPage reading a selected file client-side); polyfill it via FileReader, which
// jsdom does support, so component tests can simulate a real file selection.
if (typeof File !== 'undefined' && !File.prototype.text) {
  File.prototype.text = function (this: File) {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result ?? ''));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(this);
    });
  };
}

// jsdom (as of 25.x) reflects <dialog>'s `open` attribute/property generically, but doesn't
// implement the imperative `showModal()`/`show()`/`close()` methods at all (not even as no-ops) -
// used by the shared ConfirmDialog primitive (add-uplift-frontend-ux). Polyfilled minimally: just
// enough for the component's own open/close lifecycle and `close` event to be testable. This
// can't replicate a real browser's native focus-trap/::backdrop - ConfirmDialog implements its
// own keyboard focus trap for exactly that reason, rather than relying on jsdom to prove it.
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.show = function (this: HTMLDialogElement) {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement, returnValue?: string) {
    const wasOpen = this.hasAttribute('open');
    if (returnValue !== undefined) this.returnValue = returnValue;
    this.removeAttribute('open');
    if (wasOpen) this.dispatchEvent(new Event('close'));
  };
}
