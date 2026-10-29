import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import { NoiseActions, UnstableQuestions } from "./measurement-noise";

vi.mock("@/hooks/use-agents", () => ({
  useAgentsOfKind: () => ({ agents: [], isLoading: false, error: null }),
}));

it("points the rules a criterion's words suggest at the grading tab", () => {
  render(<NoiseActions session={SESSION} />);
  expect(
    screen.getByRole("link", { name: "Check length and format with a rule instead of the judge" }),
  ).toHaveAttribute("href", "/datasets/d1?tab=cases");
  expect(screen.getByText(/Under each criterion a rule can check/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "the grading tab" })).toHaveAttribute(
    "href",
    "/datasets/d1?tab=grading",
  );
  expect(screen.getByRole("link", { name: "Grade with a stronger judge model" })).toHaveAttribute(
    "href",
    "/datasets/d1?tab=grading",
  );
});

it("lists no unstable questions when the session kept none", () => {
  const { container } = render(
    <UnstableQuestions
      noise={{
        held_out: 10,
        unstable: 3,
        examples: [],
        baseline_low: null,
        baseline_high: null,
        baseline_spread: 0,
        by_attempt: [],
        noisy: true,
        within: 3,
        shared: 10,
        between: 0,
        too_few_shared: false,
      }}
    />,
  );
  expect(container).toBeEmptyDOMElement();
});
