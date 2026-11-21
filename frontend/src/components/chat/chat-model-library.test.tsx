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
  expect(screen.getByRole("option", { name: "Claude" })).toBeVisible();
  expect(screen.queryByText("anthropic/claude")).not.toBeInTheDocument();
  await userEvent.type(screen.getByRole("combobox"), "anthropic/claude");
  await userEvent.click(screen.getByRole("option", { name: "Claude" }));
  expect(p.onModelChange).toHaveBeenCalledWith("anthropic/claude");
  await userEvent.clear(screen.getByRole("combobox"));
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
  expect(screen.queryByRole("button", { name: "Add provider key" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "Key" }));
  expect(screen.getByRole("button", { name: "Add provider key" })).toBeVisible();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});

it("keeps existing key selection in its own keyboard-accessible tab", async () => {
  const user = userEvent.setup();
  render(<ChatModelLibrary {...props()} credentialPicker={<button>Choose stored key</button>} />);
  expect(screen.queryByRole("button", { name: "Choose stored key" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "Saved models" }));
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Key" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("button", { name: "Choose stored key" })).toBeVisible();
});

it("keeps cached models visible while their metadata refreshes", async () => {
  const p = props();
  const { rerender } = render(<ChatModelLibrary {...p} catalogRefreshing />);
  const model = screen.getByRole("option", { name: /Claude/ });
  expect(model).toBeVisible();
  expect(model).toHaveAttribute("aria-disabled", "true");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  await userEvent.click(model);
  expect(p.onModelChange).not.toHaveBeenCalled();

  rerender(<ChatModelLibrary {...p} catalogRefreshing={false} />);
  await userEvent.click(model);
  expect(p.onModelChange).toHaveBeenCalledWith("anthropic/claude");
});

it("keeps saved models in the catalog and marks the active one", async () => {
  const p = props();
  const saved = {
    id: "saved-claude",
    provider: "openrouter",
    model: "anthropic/claude",
    label: "My Claude",
    secret_id: "key",
    params: {},
    fallback_profile_ids: [],
  };
  render(
    <ChatModelLibrary
      {...p}
      model={saved.model}
      profileId={saved.id}
      profiles={[saved, { ...saved, id: "saved-custom", model: "other/custom", label: "Custom" }]}
    />,
  );
  const model = screen.getByRole("option", { name: /Claude/ });
  expect(within(model).getByLabelText("Selected")).toBeInTheDocument();
  await userEvent.click(model);
  expect(p.onModelChange).toHaveBeenCalledWith(saved.model);
  expect(screen.getByRole("option", { name: "Custom" })).toBeVisible();

  await userEvent.click(screen.getByRole("tab", { name: "Saved models" }));
  expect(screen.getByRole("option", { name: /My Claude/ })).toBeVisible();
});

it("shows familiar subscriptions before API keys and keeps custom gateways folded", async () => {
  const p = props();
  render(
    <ChatModelLibrary
      {...p}
      providers={[
        ...p.providers,
        {
          id: "subscription:claude",
          label: "Claude Code",
          connected: null,
          group: "subscriptions",
          mark: "anthropic",
        },
        { id: "cliproxyapi", label: "Custom gateway", connected: false, group: "custom" },
      ]}
    />,
  );
  const subscription = screen.getByRole("button", { name: "Claude Code" });
  expect(providerMarkIn(subscription)).toBe("anthropic");
  const custom = screen
    .getByText("Advanced / custom endpoint", { selector: "summary" })
    .closest("details");
  expect(custom).not.toHaveAttribute("open");
  await userEvent.click(screen.getByText("Advanced / custom endpoint", { selector: "summary" }));
  await userEvent.click(screen.getByRole("button", { name: "Custom gateway" }));
  expect(p.onProviderChange).toHaveBeenCalledWith("cliproxyapi");
});
