import { defineConfig } from "vitest/config";

/**
 * Provides Vitest configuration for focused service-level tests.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    coverage: {
      reporter: ["text", "html"],
    },
  },
});
