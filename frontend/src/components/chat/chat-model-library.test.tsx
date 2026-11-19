import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ChatModelLibrary } from "./chat-model-library";
import { providerMarkIn } from "@/test-utils/brand-marks";

function props() {
  return {
    providers: [
      { id: "openai", label: "openai", connected: false },
      { id: "openrouter", label: "OpenRouter", connected: true },
    ],
    providerId: "openrouter",
    model: "",
    models: [{ id: "anthropic/claude", name: "Anthropic: Claude" }],
    profiles: [],
    loading: false,
    applying: false,
    disabled: false,
    onProviderChange: vi.fn(),
    onModelChange: vi.fn(),
    onProfileChange: vi.fn(),
    credentialForm: null,
    failure: null,
  };
}
it("puts connected providers first with capitalized names and brand marks", () => {
  render(<ChatModelLibrary {...props()} />);
  const buttons = within(screen.getByRole("group", { name: "Provider" })).getAllByRole("button");
  expect(buttons[0]).toHaveTextContent("OpenRouter");
  expect(buttons[1]).toHaveTextContent("Openai");
  expect(providerMarkIn(buttons[0]!)).toBe("openrouter");
  expect(providerMarkIn(buttons[1]!)).toBe("openai");
});
it("searches model names, supports an unlisted model ID, and applies only on confirmation", async () => {
  const p = props();
  render(<ChatModelLibrary {...p} />);
  await userEvent.click(screen.getByRole("option", { name: /Claude/ }));
  expect(p.onModelChange).toHaveBeenCalledWith("anthropic/claude");
  await userEvent.type(screen.getByRole("combobox"), "other/new");
  expect(screen.queryByRole("option", { name: /Claude/ })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("option", { name: "Use model ID: other/new" }));
  expect(p.onModelChange).toHaveBeenLastCalledWith("other/new");
  expect(screen.queryByRole("button", { name: "Run on this model" })).not.toBeInTheDocument();
});
it("clears a search when changing provider and keeps credential forms in the pane", async () => {
  const p = props();
  render(<ChatModelLibrary {...p} credentialForm={<button>Add provider key</button>} />);
  await userEvent.type(screen.getByRole("combobox"), "claude");
  await userEvent.click(screen.getByRole("button", { name: /Openai/ }));
  expect(p.onProviderChange).toHaveBeenCalledWith("openai");
  expect(screen.getByRole("combobox")).toHaveValue("");
  expect(screen.getByRole("button", { name: "Add provider key" })).toBeVisible();
});
