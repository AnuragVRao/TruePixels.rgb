import React from 'react';
import { Moon, Sun } from 'lucide-react';
import { useTheme } from '../lib/theme';

/** Light (default) / dark switch; the choice is remembered in this browser. */
export const ThemeToggle: React.FC = () => {
  const [theme, toggle] = useTheme();
  const dark = theme === 'dark';
  return (
    <button type="button" onClick={toggle} aria-pressed={dark}
            title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
            aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
            className="w-8 h-8 shrink-0 flex items-center justify-center rounded-xl border border-border bg-card text-foreground/80 hover:text-foreground hover:border-primary">
      {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
    </button>
  );
};
