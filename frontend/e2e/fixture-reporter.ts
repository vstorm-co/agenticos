import type { FullConfig, Reporter, Suite, TestCase, TestResult } from "@playwright/test/reporter";

/**
 * Say out loud when a red run was a precondition rather than a regression.
 *
 * `setup` and `seed` are project *dependencies*, so when a step in one of them
 * fails Playwright does not run the projects that depend on it. What the log
 * then says is `1 failed`, `7 passed`, and — in one unlabelled line somewhere
 * above the failure — `17 did not run`. On a pull request that arrives as a red
 * `e2e` job, which reads exactly like a broken feature. It is not: **no product
 * spec ran at all.**
 *
 * That cost three separate diagnoses on three different branches in one day
 * (#132), and the reason each of them cost anything is that the summary said
 * nothing about which half of the suite the failure was in. So this adds the one
 * sentence the reader needs, after everything else has printed, and — under CI —
 * as a GitHub error annotation, which shows on the checks page without anybody
 * opening a log.
 *
 * It reports; it never changes the outcome. A failed fixture already fails the
 * run.
 */
export default class FixtureReporter implements Reporter {
  /** The names of the setup/seed steps that failed, in the order they failed. */
  private readonly failures: string[] = [];
  /** Test ids that reported a result — with retries, a test may report twice. */
  private readonly reported = new Set<string>();
  /** Every test the run intended to execute, after `--grep` and friends. */
  private planned = 0;

  onBegin(_config: FullConfig, suite: Suite): void {
    this.planned = suite.allTests().length;
  }

  onTestEnd(test: TestCase, result: TestResult): void {
    this.reported.add(test.id);
    if (result.status !== "failed" && result.status !== "timedOut") return;

    // The project, not the file: which file a fixture lives in is a detail, but
    // "this was a dependency" is the whole point of the message below.
    const project = test.parent.project()?.name;
    if (project !== "setup" && project !== "seed") return;

    const file = test.location.file.split("/").pop();
    this.failures.push(`[${project}] ${file}:${test.location.line} › ${test.title}`);
  }

  onEnd(): void {
    if (this.failures.length === 0) return;

    const neverRan = this.planned - this.reported.size;
    const rule = "─".repeat(78);
    const lines = [
      "",
      rule,
      "  A FIXTURE FAILED, SO THE SUITE DID NOT TEST THE PRODUCT.",
      "",
      ...this.failures.map((failure) => `    ${failure}`),
      "",
      `  ${neverRan} spec${neverRan === 1 ? "" : "s"} never ran: they depend on the project above, so`,
      "  Playwright skipped them. Nothing here says a feature is broken. Read the",
      "  failure above, and treat a green re-run as evidence about the fixture",
      "  rather than about the branch.",
      rule,
      "",
    ];
    process.stdout.write(`${lines.join("\n")}\n`);

    if (process.env.CI) {
      // A workflow command has to be one line, so the newlines are escaped the
      // way GitHub wants them. This is what puts the sentence on the checks page.
      const body = [
        `${neverRan} spec(s) never ran — the failure is in a fixture project, not in a product spec.`,
        ...this.failures,
      ].join("%0A");
      process.stdout.write(`::error title=E2E fixture failed, no product spec ran::${body}\n`);
    }
  }
}
