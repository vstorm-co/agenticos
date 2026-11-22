import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { ChatHomeOverrides } from "@/lib/console-experience-api";
import { expect, it, vi } from "vitest";
import { ChatHomeControls } from "./chat-home-controls";
import { DEFAULT_CHAT_HOME } from "@/lib/console-experience-api";

it("changes each availability item independently", async () => {
  const change = vi.fn();
  render(<ChatHomeControls mode="availability" value={{ inbox: false }} onChange={change} />);
  expect(screen.getByRole("switch", { name: "Inbox preview" })).not.toBeChecked();
  expect(screen.getByRole("switch", { name: "Prompt suggestions" })).toBeChecked();
  await userEvent.click(screen.getByRole("switch", { name: "Welcome greeting" }));
  expect(change).toHaveBeenCalledWith("greeting", false);
});
it("shows inheritance and prevents personal choices from bypassing availability", async () => {
  const change = vi.fn();
  function Harness() {
    const [value, setValue] = useState<ChatHomeOverrides>({ starters: false });
    return (
      <ChatHomeControls
        mode="inheritance"
        value={value}
        availability={{ ...DEFAULT_CHAT_HOME, inbox: false }}
        defaults={{ ...DEFAULT_CHAT_HOME, greeting: false }}
        onChange={(field, next) => {
          change(field, next);
          setValue((current) => ({ ...current, [field]: next }));
        }}
      />
    );
  }
  render(<Harness />);
  expect(screen.getByRole("combobox", { name: "Inbox preview" })).toBeDisabled();
  expect(screen.getByText("Unavailable for this deployment.")).toBeVisible();
  const greeting = screen.getByRole("combobox", { name: "Welcome greeting" });
  expect(greeting).toHaveTextContent("Inherit (hidden)");
  await userEvent.click(greeting);
  await userEvent.click(screen.getByRole("option", { name: "Show" }));
  expect(change).toHaveBeenLastCalledWith("greeting", true);
  await userEvent.click(greeting);
  await userEvent.click(screen.getByRole("option", { name: "Inherit (hidden)" }));
  expect(change).toHaveBeenLastCalledWith("greeting", null);
});
