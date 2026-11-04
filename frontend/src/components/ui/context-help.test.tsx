import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { ContextHelp } from "./context-help";

it("discloses guidance by keyboard and returns focus when dismissed", async () => {
  const user = userEvent.setup();
  render(<ContextHelp>Instructions for this page</ContextHelp>);
  expect(screen.queryByText("Instructions for this page")).not.toBeInTheDocument();
  const trigger = screen.getByRole("button", { name: "More information" });
  trigger.focus();
  await user.keyboard("{Enter}");
  expect(await screen.findByText("Instructions for this page")).toBeVisible();
  await user.keyboard("{Escape}");
  expect(screen.queryByText("Instructions for this page")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});
