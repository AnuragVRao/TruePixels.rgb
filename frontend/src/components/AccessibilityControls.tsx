import React, { useEffect, useRef, useState } from 'react';
import { Accessibility, Contrast, X } from 'lucide-react';
import { TEXT_SIZES, useTextSize, useTheme, type TextSize } from '../lib/theme';

const SIZE_LABEL: Record<TextSize, string> = { small: 'A−', normal: 'A', large: 'A+', larger: 'A++' };
const SIZE_NAME: Record<TextSize, string> = {
  small: 'Smaller text', normal: 'Default text size', large: 'Larger text', larger: 'Largest text',
};

/**
 * The header's accessibility controls (DBIM §5.4, §8): text size and a dark,
 * high-contrast theme. Both are remembered in this browser only.
 */
export const AccessibilityControls: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [theme, toggleTheme] = useTheme();
  const [size, setSize] = useTextSize();
  const box = useRef<HTMLDivElement>(null);
  const dark = theme === 'dark';

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    const onClick = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onClick);
    };
  }, [open]);

  return (
    <div className="relative" ref={box}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="true"
              aria-controls="a11y-panel" title="Accessibility controls" aria-label="Accessibility controls"
              className="w-10 h-10 shrink-0 flex items-center justify-center rounded-md border border-border bg-card text-primary hover:bg-accent">
        <Accessibility className="w-5 h-5" aria-hidden="true" />
      </button>
      {open && (
        <div id="a11y-panel" role="group" aria-label="Accessibility controls"
             className="fixed inset-x-4 top-20 sm:absolute sm:inset-x-auto sm:top-auto sm:right-0 sm:mt-2 sm:w-72 rounded-lg border border-border bg-popover text-popover-foreground shadow-lg p-4 z-40 space-y-4">
          <div className="flex items-center justify-between">
            <p className="flex items-center gap-2 font-semibold text-sm">
              <Accessibility className="w-5 h-5 text-primary" aria-hidden="true" /> Accessibility controls
            </p>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close accessibility controls" title="Close"
                    className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-muted">
              <X className="w-5 h-5" aria-hidden="true" />
            </button>
          </div>
          <div>
            <p className="text-xs font-semibold text-muted-foreground mb-2">Text size</p>
            <div className="grid grid-cols-4 gap-2">
              {TEXT_SIZES.map((s) => (
                <button key={s} type="button" onClick={() => setSize(s)} aria-pressed={size === s}
                        title={SIZE_NAME[s]} aria-label={SIZE_NAME[s]}
                        className={`py-2 rounded-md border text-sm font-semibold ${
                          size === s ? 'bg-primary text-primary-foreground border-primary' : 'bg-card border-border hover:bg-accent'}`}>
                  {SIZE_LABEL[s]}
                </button>
              ))}
            </div>
          </div>
          <button type="button" onClick={toggleTheme} aria-pressed={dark}
                  className={`w-full flex items-center justify-center gap-2 py-2 rounded-md border text-sm font-semibold ${
                    dark ? 'bg-primary text-primary-foreground border-primary' : 'bg-card border-border hover:bg-accent'}`}>
            <Contrast className="w-5 h-5" aria-hidden="true" /> Dark contrast {dark ? 'on' : 'off'}
          </button>
        </div>
      )}
    </div>
  );
};
