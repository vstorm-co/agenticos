import { describe, expect, it } from "vitest";

import { DOCS_URL, LEARN_URL, reportProblemUrl } from "./help-links";

describe("help links", () => {
  it("points at the published docs site and its Learn track", () => {
    expect(DOCS_URL).toBe("https://vstorm-co.github.io/agenticos/");
    expect(LEARN_URL).toBe("https://vstorm-co.github.io/agenticos/learn/");
  });

  it("opens the bug-report form with the running version filled in", () => {
    expect(reportProblemUrl("1.52.0")).toBe(
      "https://github.com/vstorm-co/agenticos/issues/new?template=bug_report.yml&version=v1.52.0",
    );
  });
});
