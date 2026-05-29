// Flat config (ESLint 9+). Enforces the "no cross-module impl/ imports" rule
// from VRAI_Faces_Claude_Code_Guide.md §1.
import tseslint from '@typescript-eslint/eslint-plugin';
import tsparser from '@typescript-eslint/parser';
import importPlugin from 'eslint-plugin-import';

export default [
  {
    files: ['src/**/*.ts', 'src/**/*.tsx', 'test/**/*.ts'],
    languageOptions: {
      parser: tsparser,
      parserOptions: {
        project: './tsconfig.json',
        ecmaVersion: 2022,
        sourceType: 'module',
      },
    },
    plugins: {
      '@typescript-eslint': tseslint,
      import: importPlugin,
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      // Forbid cross-module imports into another module's impl/.
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['**/modules/*/impl/*', '../*/impl/*', '../../*/impl/*'],
              message:
                'Cross-module imports must go through the module barrel (index.ts). ' +
                'Importing another module\'s impl/ is a contract break — see ' +
                'VRAI_Faces_Claude_Code_Guide.md §1.',
            },
          ],
        },
      ],
    },
  },
];
