import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { EvalSuiteCheck } from "@/types/eval-runs";
import { SuiteCheckVerdict } from "./suite-check-verdict";

function check(overrides: Partial<EvalSuiteCheck> = {}): EvalSuiteCheck {
  return {
    suite_id: "suite-1",
    name: "Nightly",
    suite_exists: true,
    status: "failed",
    reasons: [{ code: "pass_rate_below", value: 0.5, limit: 0.9, detail: null }],
    ...overrides,
  };
}

describe("SuiteCheckVerdict", () => {
  it("words the verdict and its reasons as the suite's own results are", () => {
    render(<SuiteCheckVerdict agentId="agent-1" check={check()} />);

    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Pass rate 50% is below the 90% minimum.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Nightly" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=evals",
    );
  });

  it("names a suite that has gone without offering to open it", () => {
    render(
      <SuiteCheckVerdict
        agentId="agent-1"
        check={check({ suite_exists: false, status: "inconclusive", reasons: [] })}
      />,
    );

    expect(screen.getByText("Inconclusive")).toBeInTheDocument();
    expect(screen.getByText("Nightly")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("says nothing until the run completes", () => {
    const { container } = render(
      <SuiteCheckVerdict agentId="agent-1" check={check({ status: null })} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});

it("explains that a baseline-only check does not pass or promote", () => {
  render(
    <SuiteCheckVerdict agentId="agent-1" check={check({ status: "baseline_set", reasons: [] })} />,
  );
  expect(screen.getByText("Baseline set")).toBeVisible();
  expect(screen.getByText(/it does not pass or promote a version/)).toBeVisible();
});
