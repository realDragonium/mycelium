import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

// Findings that predate the build are recorded in eslint-suppressions.json and
// only those are tolerated; anything new fails. Fix one, then run
// `npm run lint -- --prune-suppressions` so the file only shrinks. What is in
// there today: react-hooks/set-state-in-effect and immutability, the React
// Compiler rules, in the screens ported unchanged from the former /ui app (the
// graphs, activity, glossary, names, documents). They flag fetch-then-setState
// effects that work correctly without the compiler; new code loads through
// useAsync (ui/use-async.ts), which satisfies them.
export default tseslint.config(
  { ignores: ['node_modules'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: globals.browser },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-hooks/exhaustive-deps': 'error',
      'no-empty': ['error', { allowEmptyCatch: true }],
      '@typescript-eslint/no-unused-expressions': ['error', { allowTernary: true, allowShortCircuit: true }],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
    },
  },
);
