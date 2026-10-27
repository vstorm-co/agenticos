import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import { WizardNav, WizardSteps } from "./wizard-steps";

const STEPS = [
  { id: "source", label: "Pick source" },
  { id: "configure", label: "Configure" },
  { id: "schedule", label: "Schedule" },
];

describe("the wizard's steps", () => {
  it("marks the step on screen, checks the ones behind it and numbers the rest", () => {
    const { container } = render(<WizardSteps steps={STEPS} current="configure" />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[1]).toHaveAttribute("aria-current", "step");
    expect(items[0]).not.toHaveAttribute("aria-current");
    // The finished step shows a check rather than its number; the next shows "3".
    expect(items[0]?.querySelector("svg")).not.toBeNull();
    expect(items[2]).toHaveTextContent("3");
    expect(screen.getByText("Configure")).toHaveClass("text-foreground");
    expect(container.querySelector(".uppercase")).toBeNull();
  });

  it("names every step in words, as written", () => {
    render(<WizardSteps steps={STEPS} current="source" />);

    expect(screen.getByText("Pick source")).toBeInTheDocument();
    expect(screen.getByText("Schedule")).toBeInTheDocument();
  });

  it("compact, is a dot per step with only the current one written out", () => {
    const { container } = render(<WizardSteps steps={STEPS} current="configure" compact />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[1]).toHaveAttribute("aria-current", "step");
    // Every step is still named for a screen reader; on screen only the current one.
    expect(items.map((item) => item.textContent)).toEqual(["Pick source", "Configure", "Schedule"]);
    expect(container.querySelector("ol + span")).toHaveTextContent(/^Configure$/);
  });
});

it("lets a person inspect any step while retaining its actual recorded state", async () => {
  const user = userEvent.setup();
  const onSelect = vi.fn();
  render(
    <WizardSteps
      responsive
      steps={[
        { id: "source", label: "Source", status: "skipped", statusLabel: "Skipped" },
        { id: "work", label: "Check", status: "running", statusLabel: "Running" },
        { id: "decision", label: "Accept", status: "needs_you", statusLabel: "Needs you" },
        { id: "done", label: "Questions", status: "done", statusLabel: "Done" },
        { id: "later", label: "Later", status: "pending", statusLabel: "Not started" },
      ]}
      current="decision"
      onSelect={onSelect}
    />,
  );
  const source = screen.getByRole("button", { name: "Source" });
  expect(source).toHaveAccessibleDescription("Skipped");
  expect(screen.getByRole("button", { name: "Check" })).toHaveAccessibleDescription("Running");
  await user.click(source);
  expect(onSelect).toHaveBeenCalledWith("source");
});
it("keeps a step that is not open yet in the tab order but out of reach", async () => {
  const onSelect = vi.fn();
  render(
    <WizardSteps
      steps={[
        { id: "source", label: "Pick source", status: "done" },
        { id: "configure", label: "Configure", status: "pending", disabled: true },
      ]}
      current="source"
      onSelect={onSelect}
    />,
  );
  const locked = screen.getByRole("button", { name: "Configure" });
  expect(locked).toHaveAttribute("aria-disabled", "true");
  expect(locked).not.toBeDisabled();
  await userEvent.click(locked);
  expect(onSelect).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Pick source" })).not.toHaveAttribute("aria-disabled");
});
it("supports keyboard selection and status descriptions in a compact stepper", async () => {
  const user = userEvent.setup();
  const onSelect = vi.fn();
  render(
    <WizardSteps
      compact
      steps={[
        { id: "first", label: "First", status: "done", statusLabel: "Done" },
        { id: "second", label: "Second", status: "pending", statusLabel: "Not started" },
      ]}
      current="first"
      onSelect={onSelect}
    />,
  );
  await user.tab();
  await user.keyboard("{Enter}");
  expect(onSelect).toHaveBeenCalledWith("first");
  expect(screen.getByRole("button", { name: "Second" })).toHaveAccessibleDescription("Not started");
});

it("keeps cancellation available but prevents moving a step back during submission", async () => {
  const user = userEvent.setup();
  const back = vi.fn();
  const next = vi.fn();
  const view = render(
    <WizardNav
      backLabel="Back"
      onBack={back}
      nextLabel="Publish"
      onNext={next}
      busy
      backIsStep
      busyLabel="Publishing"
    />,
  );
  expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Publishing" })).toBeDisabled();
  view.rerender(
    <WizardNav backLabel="Cancel" onBack={back} nextLabel="Publish" onNext={next} busy />,
  );
  expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(back).toHaveBeenCalledOnce();
  view.rerender(
    <WizardNav backLabel="Back" onBack={back} nextLabel="Publish" onNext={next} isLast />,
  );
  await user.click(screen.getByRole("button", { name: "Publish" }));
  expect(next).toHaveBeenCalledOnce();
});
it("keeps unannotated steps selectable with their normal labels", async () => {
  const user = userEvent.setup();
  const select = vi.fn();
  render(<WizardSteps steps={STEPS} current="source" compact onSelect={select} />);
  await user.click(screen.getByRole("button", { name: "Configure" }));
  expect(select).toHaveBeenCalledWith("configure");
  expect(screen.getByRole("button", { name: "Configure" })).not.toHaveAttribute("aria-describedby");
});
