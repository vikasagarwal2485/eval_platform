import { useEffect, useState } from 'react';

interface Props {
  id: string;
  label: string;
  value: number;
  onChange: (n: number) => void;
  min: number;
  max: number;
  step?: number | 'any';
}

/**
 * Number input that keeps what the user is typing (so the field can be cleared and retyped) and only
 * clamps to [min, max] when focus leaves. In-range values are propagated immediately.
 */
export default function NumberField({ id, label, value, onChange, min, max, step }: Props) {
  const [text, setText] = useState(String(value));

  useEffect(() => {
    if (Number(text) !== value) setText(String(value)); // external change (e.g. reset)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const commit = (raw: string) => {
    const n = Number(raw);
    if (raw.trim() !== '' && !Number.isNaN(n) && n >= min && n <= max) onChange(n);
  };

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        value={text}
        aria-invalid={text.trim() === '' || Number(text) < min || Number(text) > max}
        onChange={(e) => {
          setText(e.target.value);
          commit(e.target.value);
        }}
        onBlur={() => {
          const n = Number(text);
          const clamped =
            text.trim() === '' || Number.isNaN(n) ? value : Math.min(max, Math.max(min, n));
          setText(String(clamped));
          if (clamped !== value) onChange(clamped);
        }}
      />
    </div>
  );
}
