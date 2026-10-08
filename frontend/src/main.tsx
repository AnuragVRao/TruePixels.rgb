import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
// Fonts are bundled and served from this origin (Phase 6): no request to
// Google Fonts, so the CSP can stay at style-src/font-src 'self'.
import '@fontsource/dm-sans/400.css';
import '@fontsource/dm-sans/500.css';
import '@fontsource/dm-sans/600.css';
import '@fontsource/dm-sans/700.css';
import '@fontsource/dm-sans/800.css';
import '@fontsource/space-mono/400.css';
import '@fontsource/space-mono/700.css';
import './index.css';
import { applyTheme, storedTheme } from './lib/theme';

// Before the first render, so a dark-mode visitor never sees a light flash.
// (An inline script in index.html would be blocked by the CSP.)
applyTheme(storedTheme());

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
