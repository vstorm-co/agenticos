import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { Switch } from "./switch";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip";

it("preserves the switch state when a tooltip supplies its own data-state", async () => {
  render(
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Switch aria-label="Pause routine" />
        </TooltipTrigger>
        <TooltipContent>Pause</TooltipContent>
      </Tooltip>
    </TooltipProvider>,
  );
  const control = screen.getByRole("switch", { name: "Pause routine" });
  expect(control).toHaveAttribute("aria-checked", "false");
  await userEvent.click(control);
  expect(control).toHaveAttribute("aria-checked", "true");
  await userEvent.keyboard(" ");
  expect(control).toHaveAttribute("aria-checked", "false");
});
