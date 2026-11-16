import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { WidgetEmptyBody, WidgetErrorBody } from "./widget-states";

it("keeps empty-state guidance available behind its summary", async () => {
  const { container } = render(
    <WidgetEmptyBody title="No runs yet" description="Start an agent to see its runs." />,
  );
  const summary = screen.getByText("No runs yet");
  expect(container.querySelector("details")).not.toHaveAttribute("open");
  await userEvent.click(summary);
  expect(container.querySelector("details")).toHaveAttribute("open");
  expect(screen.getByText("Start an agent to see its runs.")).toBeVisible();
});

it("keeps failures and retry visible rather than collapsing them", () => {
  const { container } = render(<WidgetErrorBody onRetry={() => {}} />);
  expect(container.querySelector("details")).toBeNull();
  expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
});
