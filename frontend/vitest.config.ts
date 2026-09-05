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
    /*
     * Raised from vitest's 5s default, because 5s is not a deadline this suite
     * can hold and the machine decides which spec misses it.
     *
     * Measured over all 4941 tests, on ten cores (#862). Quiet, the slowest
     * test is 1.7s bare and 2.9s under v8 instrumentation. At 32 busy loops
     * beside it — the load the issue was filed from — the slowest is 5.4s bare
     * and 6.1s instrumented, and both runs went red: three tests each, and a
     * different three, because which files share a worker is decided on
     * timing. Instrumentation is one multiplier of several and the smaller
     * one; scheduling latency is the rest, which is why this is not
     * conditional on `--coverage`. A timeout the fast loop and the gate
     * disagree about is one that cannot reproduce the gate.
     *
     * 15s is 2.5x the worst duration measured under that load, and the number
     * `playwright.config.ts` already writes down for the same class of
     * problem. A test that genuinely hangs still fails — ten seconds later
     * than it used to, on the one run where that is the answer rather than a
     * lie about the diff.
     */
    testTimeout: 15_000,
    server: {
      deps: {
        // `next-intl/middleware` imports `next/server` bare, which Node's ESM
        // resolver cannot answer for an externalized dependency ("did you mean
        // next/server.js"). Transformed by Vite instead, the import resolves and
        // `src/middleware.test.ts` can drive the real middleware rather than a
        // stand-in for it.
        inline: ["next-intl"],
      },
    },
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      // Widened one layer at a time, and everything listed is at 100%. The list
      // is what is *finished*, not what is worth testing: the chat components are
      // next, then the smaller component directories —
      // `docs/plans/frontend-coverage.md` tracks the rest.
      //
      // Pages are last on purpose. They are composition, and mounting one to
      // move a number tests nothing the E2E suite does not already fail on.
      include: [
        "src/app/api/**",
        "src/lib/**",
        "src/stores/**",
        "src/hooks/**",
        "src/components/agents/**/*.{ts,tsx}",
        // The sandbox cards only, not the whole widget directory: the twenty-seven
        // cards #149 added are outside the gate, and pulling them in with a
        // directory glob would make this branch responsible for covering them.
        "src/components/dashboard/widgets/sandbox-*.tsx",
        // The routines card, held to the gate by #594's own "done when".
        "src/components/dashboard/widgets/routines.tsx",
        "src/components/orgs/**/*.tsx",
        "src/components/runs/**/*.tsx",
        "src/components/sandboxes/**/*.tsx",
        // One file viewer for every surface (#136). Held to the gate because what
        // it replaced was: three of the four implementations sat under
        // `components/sandboxes/**` and one under `chat/`, all already at 100%, so
        // moving them out of the list would have been a coverage regression
        // dressed up as a refactor.
        "src/components/files/**/*.tsx",
        "src/components/chat/usage-strip.tsx",
        "src/components/chat/attachment-card.tsx",
        "src/components/chat/tool-results/**/*.tsx",
        "src/components/chat/chart-message.tsx",
        "src/components/chat/chat-controls.tsx",
        "src/components/chat/connect-services-card.tsx",
        "src/components/chat/your-connections.tsx",
        "src/components/chat/chat-empty-state.tsx",
        "src/components/chat/conversation-filters.tsx",
        "src/components/chat/copy-button.tsx",
        "src/components/chat/delegation-panel.tsx",
        "src/components/chat/file-preview-panel.tsx",
        "src/components/chat/markdown-content.impl.tsx",
        "src/components/chat/markdown-content.tsx",
        "src/components/chat/message-cost.tsx",
        "src/components/chat/message-item.tsx",
        "src/components/chat/message-list.tsx",
        "src/components/chat/pending-messages.tsx",
        "src/components/chat/plan-checklist.tsx",
        "src/components/chat/plan-strip.tsx",
        "src/components/chat/rating-buttons.tsx",
        "src/components/chat/slash-command-palette.tsx",
        "src/components/chat/share-dialog.tsx",
        "src/components/chat/slash-commands.ts",
        "src/components/chat/sources-panel.tsx",
        "src/components/chat/tool-call-card.tsx",
        "src/components/chat/tool-approval-dialog.tsx",
        "src/components/chat/workspace-files.tsx",
        "src/components/sharing/**/*.tsx",
        "src/components/skills/**/*.tsx",
        "src/components/context/**/*.tsx",
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
      // A ratchet, not a target. Every statement, line and function in the set
      // above is covered, and the gate says so: an uncovered line is a build
      // failure, not a number that drifts. Never lower these to make a red build
      // green - either the line is worth a test or it is worth deleting.
      //
      // Branches sit below 100 for one reason: TypeScript-required guards whose
      // other half no caller can reach (`event.target.files ?? []`,
      // `pop() ?? "…"`, a `?? ""` on a value the early return already proved).
      // Each is a narrowing, not a behaviour, and faking one would mean testing
      // the type checker. What is *left* to widen is the `include` list, not
      // these numbers - see `docs/plans/frontend-coverage.md`.
      thresholds: {
        statements: 100,
        // 97.5, down from 98, and the code did not get worse - the ruler
        // changed. coverage-v8 4 counts the untaken side of `??` and `||`,
        // which version 2 did not, and this codebase reaches for that idiom
        // everywhere: `activeOrgId ?? ""`, `error.message || "Failed to …"`,
        // `path.split(".").pop()?.toLowerCase() ?? ""`. Eighty-eight of them
        // across forty-seven files went from uncounted to uncovered on the
        // upgrade, with no test and no line of source changing.
        //
        // Writing eighty-eight tests that assert a fallback string appears
        // would buy the number back and nothing else. Statements, functions
        // and lines stay at 100, which is where a real gap shows up; this one
        // is set just under the measured 97.51 so it still ratchets.
        branches: 97.5,
        functions: 100,
        lines: 100,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
