import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { Improvement } from "@/types/improvement";
import { StepDecisions } from "./step-decisions";

const AT = "2026-10-26T09:30:00Z";
const event = (action: string, actor_name: string | null) => ({
  action,
  at: AT,
  stage: null,
  status: null,
  reason: null,
  actor_user_id: actor_name ? "u1" : null,
  actor_name,
});
const SESSION_WITH: Improvement = {
  ...SESSION,
  timeline: [
    event("improvement.started", "Ada"),
    event("improvement.evidence_decided", "Ada"),
    event("improvement.selection_confirmed", "Ben"),
    event("improvement.verdict", null),
    event("improvement.published", null),
    event("improvement.round_selected", "Ben"),
  ],
};

it("names who decided what on the step a person opens", () => {
  const view = render(<StepDecisions session={SESSION_WITH} step="understand" />);
  expect(screen.getByRole("region", { name: "Decided here" })).toBeInTheDocument();
  expect(screen.getByText(/^Ada started this session · /)).toBeInTheDocument();
  expect(screen.getByText(/^Ada moved or ignored an example · /)).toBeInTheDocument();
  expect(screen.queryByText(/Ben/)).toBeNull();
  view.rerender(<StepDecisions session={SESSION_WITH} step="changes" />);
  expect(screen.getByText(/^Ben chose which changes to test · /)).toBeInTheDocument();
});

it("says nothing where no named person decided anything", () => {
  const { container } = render(<StepDecisions session={SESSION_WITH} step="accept" />);
  expect(container).toBeEmptyDOMElement();
  render(<StepDecisions session={SESSION_WITH} step="check" />);
  expect(screen.queryByRole("region", { name: "Decided here" })).toBeNull();
});
