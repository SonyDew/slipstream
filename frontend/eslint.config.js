import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Pages export a single component plus occasional shared helpers (for
      // example PasswordField in login.tsx); allowing constant exports keeps
      // fast refresh working without splitting files for the linter's benefit.
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // Deliberate no-op catch blocks are used where a failure is genuinely not
      // worth surfacing (clipboard, localStorage).
      'no-empty': ['error', { allowEmptyCatch: true }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'inline-type-imports' },
      ],
    },
  },
  {
    // Config files run in Node, not the browser.
    files: ['*.config.{js,ts}', 'vite.config.ts'],
    languageOptions: { globals: globals.node },
  },
  {
    // Context providers and UI primitives deliberately co-locate their hook or
    // variant helper with the component (useAuth with AuthProvider,
    // buttonVariants with Button). Splitting those files would only serve the
    // fast-refresh heuristic, so the rule is off where that pattern is the point.
    files: [
      'src/lib/*-context.tsx',
      'src/components/ui/**/*.tsx',
      'src/components/media/platform-badge.tsx',
    ],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
)
