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
