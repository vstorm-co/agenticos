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
      // A ratchet, not a target. 100% is where this is going - the numbers below
      // are wherever the suite currently stands, rounded down, so a change that
      // covers less than it removes fails the build even while the goal is still
      // some way off. Raise them as ground is gained; never lower them to make a
      // red build green.
      //
      // Standing at: 76% statements and lines, 89% branches, 67% functions. The
      // gap is `embeds-panel`, `version-history` and `channel-bots-panel`, which
      // have no tests at all, plus the partials listed in
      // `docs/plans/frontend-coverage.md`.
      thresholds: {
        statements: 76,
        branches: 89,
        functions: 67,
        lines: 76,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
