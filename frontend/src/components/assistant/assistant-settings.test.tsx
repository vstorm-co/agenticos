import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AssistantSettings } from "./assistant-settings";

afterEach(() => localStorage.clear());

it("keeps personal tips independent from organization configuration", () => {
  render(<AssistantSettings />);
  expect(screen.getByRole("switch", { name: "Show tips in speech bubbles" })).toBeChecked();
  expect(screen.queryByText("Automatic suggestions")).not.toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

it("persists the person's choice and restores silenced tips without changing it", () => {
  localStorage.setItem("assistant-bubbles", JSON.stringify({ silenced: ["/agents"], off: false }));
  render(<AssistantSettings />);
  fireEvent.click(screen.getByRole("switch", { name: "Show tips in speech bubbles" }));
  expect(JSON.parse(localStorage.getItem("assistant-bubbles")!)).toMatchObject({ off: true });
  fireEvent.click(screen.getByRole("button", { name: "Show tips again on the 1 page I silenced" }));
  expect(JSON.parse(localStorage.getItem("assistant-bubbles")!)).toMatchObject({
    off: true,
    silenced: [],
  });
  expect(screen.queryByRole("button", { name: /Show tips again/ })).not.toBeInTheDocument();
});
