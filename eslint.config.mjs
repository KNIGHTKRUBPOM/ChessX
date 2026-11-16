import tseslint from 'typescript-eslint';

export default [{
  files: ['src/**/*.ts', 'vite.config.ts'],
  ignores: ['src/lib/database.types.ts'],
  languageOptions: { parser: tseslint.parser },
  rules: {
    'no-debugger': 'error',
    'no-dupe-else-if': 'error',
    'no-unreachable': 'error',
    'no-unsafe-finally': 'error',
  },
}];
