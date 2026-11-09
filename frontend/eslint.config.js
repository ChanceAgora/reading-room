import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import hooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
export default tseslint.config(
  { ignores: ['src/generated/**', 'node_modules/**', 'playwright-report/**', 'test-results/**'] },
  js.configs.recommended, ...tseslint.configs.recommended,
  { files: ['public/**/*.js'], languageOptions: { globals: globals.browser } },
  { files: ['**/*.{ts,tsx}'], languageOptions: { globals: { ...globals.browser, ...globals.node } }, plugins: { 'react-hooks': hooks }, rules: { 'react-hooks/rules-of-hooks': 'error', 'react-hooks/exhaustive-deps': 'warn', '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }] } },
);
