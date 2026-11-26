import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip";

afterEach(() => vi.useRealTimers());

it("delays the first hint and opens the next hint immediately within the same group", () => {
  vi.useFakeTimers();
  render(
    <TooltipProvider>
      {["First", "Second"].map((name) => (
        <Tooltip key={name}>
          <TooltipTrigger>{name}</TooltipTrigger>
          <TooltipContent>{name} hint</TooltipContent>
        </Tooltip>
      ))}
    </TooltipProvider>,
  );
  fireEvent.pointerMove(screen.getByRole("button", { name: "First" }), { pointerType: "mouse" });
  act(() => vi.advanceTimersByTime(349));
  expect(screen.queryByRole("tooltip")).toBeNull();
  act(() => vi.advanceTimersByTime(1));
  expect(screen.getByRole("tooltip")).toHaveTextContent("First hint");
  fireEvent.pointerDown(screen.getByRole("button", { name: "First" }), { pointerType: "mouse" });
  fireEvent.pointerMove(screen.getByRole("button", { name: "Second" }), { pointerType: "mouse" });
  expect(screen.getByRole("tooltip")).toHaveTextContent("Second hint");
});
