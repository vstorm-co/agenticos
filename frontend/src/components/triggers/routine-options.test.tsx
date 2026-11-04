import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { RoutineOptions } from "./routine-options";

describe("progressive disclosure of routine settings", () => {
  it("keeps defaults out of the way and preserves input when collapsed", async () => {
    const { container } = render(
      <RoutineOptions>
        <input aria-label="Test budget" defaultValue="5" />
      </RoutineOptions>,
    );
    const details = container.querySelector("details")!;
    expect(details.open).toBe(false);
    await userEvent.click(screen.getByText("Advanced options"));
    expect(details.open).toBe(true);
    await userEvent.type(screen.getByLabelText("Test budget"), "0");
    await userEvent.click(screen.getByText("Advanced options"));
    expect(screen.getByLabelText("Test budget")).toHaveValue("50");
  });
  it("reveals a field that needs attention", () => {
    const { container } = render(
      <RoutineOptions invalid>
        <input aria-label="Test version" />
      </RoutineOptions>,
    );
    expect(container.querySelector("details")).toHaveAttribute("open");
  });
});

it("keeps the options open while a validation error is being corrected", () => {
  const { container, rerender } = render(
    <RoutineOptions invalid>
      <input aria-label="Test budget" />
    </RoutineOptions>,
  );
  expect(container.querySelector("details")).toHaveAttribute("open");
  rerender(
    <RoutineOptions invalid={false}>
      <input aria-label="Test budget" />
    </RoutineOptions>,
  );
  expect(container.querySelector("details")).toHaveAttribute("open");
});
