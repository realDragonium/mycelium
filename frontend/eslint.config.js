import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

// Findings that predate the build are recorded in eslint-suppressions.json and
// only those are tolerated; anything new fails. Fix one, then run
// `npm run lint -- --prune-suppressions` so the file only shrinks. What is in
// there today, and why it was not fixed during the migration:
//   - react-hooks/set-state-in-effect, refs, immutability, static-components:
//     the React Compiler rules. They flag fetch-then-setState effects, refs read
//     during render and module-level stores that work correctly without the
//     compiler; fixing them means restructuring the screens.
//   - @typescript-eslint/no-unused-vars, no-useless-assignment: dead locals and
//     components (mostly in ui/screens.tsx and ui/graph.tsx) left for the app
//     consolidation to remove.
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
