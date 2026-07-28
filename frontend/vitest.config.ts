import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.{test,spec}.{ts,tsx}"],
    exclude: ["node_modules", ".next", "e2e"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      // Scoped to the layers that hold logic worth asserting: data hooks, pure
      // helpers, stores and the components that encode a rule. Pages are
      // composition — they are covered by the E2E suite, where a broken page
      // actually fails, rather than by mounting them to move a number.
      include: [
        "src/lib/api-error.ts",
        "src/hooks/use-active-organization.ts",
        "src/hooks/use-agents.ts",
        "src/hooks/use-model-providers.ts",
        "src/hooks/use-permissions.ts",
        "src/hooks/use-runs.ts",
        "src/hooks/use-sharing.ts",
        "src/hooks/use-exposures.ts",
        "src/hooks/use-skills.ts",
        "src/components/agents/**/*.tsx",
        "src/components/sharing/**/*.tsx",
        "src/components/skills/**/*.tsx",
      ],
      exclude: [
        "node_modules",
        ".next",
        "e2e",
        "**/*.d.ts",
        "**/*.config.*",
        "**/*.test.*",
        "vitest.setup.ts",
      ],
      // Statements and branches are the meaningful bars here. The function
      // count is dominated by React Query's success and error callbacks —
      // one-line toasts whose behaviour the E2E suite exercises for real, and
      // which are not worth mounting a query client to assert individually.
      thresholds: {
        statements: 85,
        branches: 90,
        functions: 55,
        lines: 85,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
