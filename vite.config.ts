import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  server: { port: 3210, strictPort: true },
  build: {
    chunkSizeWarningLimit: 1600,
    rolldownOptions: { output: { codeSplitting: { groups: [{ name: 'phaser', test: /node_modules[\\/]phaser[\\/]/ }] } } },
  },
});
