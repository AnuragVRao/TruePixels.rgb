import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
// Fonts are bundled and served from this origin (Phase 6): no request to
// Google Fonts, so the CSP can stay at style-src/font-src 'self'.
// Noto Sans is the DBIM typeface (§4.1), in the four weights it allows.
import '@fontsource/noto-sans/400.css';
import '@fontsource/noto-sans/500.css';
import '@fontsource/noto-sans/600.css';
import '@fontsource/noto-sans/700.css';
import '@fontsource/noto-sans-mono/400.css';
import './index.css';
import { applyTextSize, applyTheme, storedTextSize, storedTheme } from './lib/theme';

// Before the first render, so a dark-mode visitor never sees a light flash.
// (An inline script in index.html would be blocked by the CSP.)
applyTheme(storedTheme());
applyTextSize(storedTextSize());

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
