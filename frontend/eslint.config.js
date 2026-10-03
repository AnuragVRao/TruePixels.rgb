// ESLint flat config (Phase 5a). react/no-danger is an error: the app never
// injects HTML - backend text (captions, error messages) renders as text.
import js from '@eslint/js';
import globals from 'globals';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'm3_dashboard', 'node_modules'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2020, globals: globals.browser },
    plugins: { react, 'react-hooks': reactHooks },
    settings: { react: { version: 'detect' } },
    rules: {
      'react/no-danger': 'error',
      'react/no-danger-with-children': 'error',
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },
  {
    // M1's original components: superseded by src/pages and no longer
    // rendered (deletion pending the owner's decision). The security rules
    // above still apply; style rules are not enforced on code we did not write.
    files: ['src/features/m1_access/**/*.tsx', 'src/components/Navbar.tsx', 'src/components/ErrorBanner.tsx'],
    rules: {
      '@typescript-eslint/no-unused-vars': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
);
