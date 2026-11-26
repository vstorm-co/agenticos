import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { OnboardingStatusCell } from "./onboarding-status-cell";

it("distinguishes an old response from a confirmed unstarted membership", () => {
  const view = render(<OnboardingStatusCell />);
  expect(screen.getByText("Not available")).toBeVisible();
  view.rerender(<OnboardingStatusCell completed_at={null} current_step={null} updated_at={null} />);
  expect(screen.getByText("Not started")).toBeVisible();
});
it.each([
  ["admin.profile", "Your profile"],
  ["member.profile", "Your profile"],
  ["preferences.language", "Which language feels natural?"],
  ["preferences.appearance", "Make the app feel like yours."],
  ["admin.models", "Choose what powers your work"],
  ["future.new-step", "Setup"],
])("translates the stored step %s into a readable label", (step, label) => {
  render(
    <OnboardingStatusCell
      completed_at={null}
      current_step={step}
      updated_at="2026-11-22T10:00:00Z"
    />,
  );
  expect(screen.getByText("In progress")).toBeVisible();
  expect(screen.getByText(label)).toBeVisible();
});
it("shows completion even for legacy records without a progress timestamp", () => {
  render(
    <OnboardingStatusCell
      completed_at="2026-11-21T10:00:00Z"
      current_step="admin.task"
      updated_at={null}
    />,
  );
  expect(screen.getByText("Completed")).toBeVisible();
  expect(screen.queryByText("In progress")).toBeNull();
  expect(document.querySelector("time")).toHaveAttribute("dateTime", "2026-11-21T10:00:00Z");
});
