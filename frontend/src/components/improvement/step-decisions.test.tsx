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
  expect(screen.getAllByRole("listitem")).toHaveLength(1);
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

it("puts each Next step press, and choosing the changes, on the step it stopped at", () => {
  const session: Improvement = {
    ...SESSION,
    timeline: [
      { ...event("improvement.next_step_taken", "Ada"), stage: "classifying" },
      { ...event("improvement.changes_chosen", "Ben"), stage: "filtering" },
      { ...event("improvement.next_step_taken", "Ben"), stage: "filtering" },
    ],
  };
  const view = render(<StepDecisions session={session} step="understand" />);
  expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
    expect.stringMatching(/^Ada asked for the changes to be written · /),
  ]);
  view.rerender(<StepDecisions session={session} step="changes" />);
  expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
    expect.stringMatching(/^Ben chose which changes to test · /),
    expect.stringMatching(/^Ben started testing the chosen changes · /),
  ]);
});

it("names who asked for another attempt and what they asked, and only this attempt's decisions", () => {
  const [first] = SESSION.iterations;
  const second = { ...first!, id: "r2", number: 2, started_at: "2026-10-26T10:00:00Z" };
  const at = (action: string, when: string) => ({ ...event(action, "Ada"), at: when });
  const session: Improvement = {
    ...SESSION,
    iteration: 2,
    iterations: [first!, { ...second, note: "Keep it short" }],
    timeline: [
      at("improvement.changes_chosen", "2026-10-26T09:40:00Z"),
      at("improvement.continuation_confirmed", "2026-10-26T10:00:01Z"),
    ],
  };
  const view = render(<StepDecisions session={session} step="changes" />);
  expect(
    screen.getByText(/^Ada asked for another attempt: “Keep it short” · /),
  ).toBeInTheDocument();
  expect(screen.queryByText(/chose which changes to test/)).toBeNull();
  view.rerender(
    <StepDecisions session={{ ...session, iterations: [first!, second] }} step="changes" />,
  );
  expect(screen.getByText(/^Ada asked for another attempt · /)).toBeInTheDocument();
  view.rerender(<StepDecisions session={session} step="check" />);
  expect(screen.queryByRole("region")).toBeNull();
});
