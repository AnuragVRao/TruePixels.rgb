import { useCallback, useState } from 'react';

/**
 * Light / dark theme. Light is the default; a choice is remembered in this
 * browser only (localStorage), and dark mode is class="dark" on <html>, which
 * switches the CSS variables in index.css.
 */
export type Theme = 'light' | 'dark';

const KEY = 'truepixels.theme';

export function storedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light'; // storage blocked (private mode, site data off): default
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark');
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      try {
        localStorage.setItem(KEY, next);
      } catch {
        // not remembered; the switch still applies to this page
      }
      return next;
    });
  }, []);
  return [theme, toggle];
}
