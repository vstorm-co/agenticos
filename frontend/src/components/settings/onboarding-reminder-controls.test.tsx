import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { OnboardingReminderControls } from "./onboarding-reminder-controls";
it("offers only inherited or approved frequencies and allows turning reminders off", async () => {
  const change = vi.fn();
  render(
    <OnboardingReminderControls
      value={{ snooze_days: 3 }}
      defaults={{ enabled: true, snooze_days: 7 }}
      onChange={change}
    />,
  );
  const frequency = screen.getByRole("combobox", { name: "Remind again after dismissing" });
  expect(frequency).toHaveTextContent("3 days");
  await userEvent.click(frequency);
  expect(screen.getAllByRole("option")).toHaveLength(4);
  await userEvent.click(screen.getByRole("option", { name: "7 days" }));
  expect(change).toHaveBeenLastCalledWith({ snooze_days: 7 });
  await userEvent.click(screen.getByRole("combobox", { name: "Setup reminders" }));
  await userEvent.click(screen.getByRole("option", { name: "Hide" }));
  expect(change).toHaveBeenLastCalledWith({ enabled: false });
});
it("keeps a deployment-disabled reminder policy visible but unchangeable", () => {
  render(
    <OnboardingReminderControls value={{ enabled: true }} available={false} onChange={vi.fn()} />,
  );
  expect(screen.getByText("Unavailable for this deployment.")).toBeVisible();
  for (const control of screen.getAllByRole("combobox")) expect(control).toBeDisabled();
});
