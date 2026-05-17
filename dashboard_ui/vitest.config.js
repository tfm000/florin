import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.js'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.js'],
      globals: false, // explicit imports; matches Vitest 4.x recommendation
      include: ['src/**/*.{test,spec}.{js,jsx}'],
      coverage: {
        provider: 'v8',
        reporter: ['text', 'lcov'],
        // Phase 1 only covers utils + hooks; component coverage lands in
        // a later phase alongside the unified chart component.
        include: ['src/utils/**', 'src/hooks/**'],
      },
    },
  }),
)
