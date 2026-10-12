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

/**
 * Accessibility control (DBIM §8): text size. The type scale in index.css is
 * in rem, so a data-text-size attribute on <html> scales every size at once.
 * Remembered in this browser only, like the theme.
 */
export type TextSize = 'small' | 'normal' | 'large' | 'larger';

export const TEXT_SIZES: TextSize[] = ['small', 'normal', 'large', 'larger'];

const TEXT_KEY = 'truepixels.textSize';

export function storedTextSize(): TextSize {
  try {
    const value = localStorage.getItem(TEXT_KEY);
    return TEXT_SIZES.includes(value as TextSize) ? (value as TextSize) : 'normal';
  } catch {
    return 'normal';
  }
}

export function applyTextSize(size: TextSize): void {
  if (size === 'normal') document.documentElement.removeAttribute('data-text-size');
  else document.documentElement.setAttribute('data-text-size', size);
}

export function useTextSize(): [TextSize, (size: TextSize) => void] {
  const [size, setSize] = useState<TextSize>(storedTextSize);
  const choose = useCallback((next: TextSize) => {
    applyTextSize(next);
    try {
      localStorage.setItem(TEXT_KEY, next);
    } catch {
      // not remembered; the size still applies to this page
    }
    setSize(next);
  }, []);
  return [size, choose];
}
