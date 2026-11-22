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
    credentialForm: null,
    failure: null,
  };
}
it("opens search from the toolbar and Escape clears it and restores focus", async () => {
  const p = props();
  render(
    <ChatModelLibrary
      {...p}
      onRefresh={vi.fn()}
      connectionLabel="person@example.com"
      credentialPicker={<span>Account settings</span>}
    />,
  );
  const search = screen.getByRole("button", { name: "Search models…" });
  expect(search).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(search.closest("[data-model-toolbar]")).toContainElement(
    screen.getByRole("button", { name: "Refresh models" }),
  );
  expect(screen.queryByText("person@example.com")).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Key" })).toHaveAttribute("title", "person@example.com");
  search.focus();
  await userEvent.keyboard("{Enter}");
  const input = screen.getByRole("combobox");
  expect(input).toHaveFocus();
  await userEvent.type(input, "missing");
  await userEvent.keyboard("{Escape}");
  expect(search).toHaveFocus();
  expect(search).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Claude" })).toBeVisible();
  await userEvent.click(search);
  await userEvent.type(screen.getByRole("combobox"), "missing");
  await userEvent.click(search);
  expect(screen.getByRole("option", { name: "Claude" })).toBeVisible();
});
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
  await userEvent.click(screen.getByRole("button", { name: "Search models…" }));
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
  const { rerender } = render(
    <ChatModelLibrary {...p} credentialForm={<button>Add provider key</button>} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Search models…" }));
  await userEvent.type(screen.getByRole("combobox"), "claude");
  await userEvent.click(screen.getByRole("button", { name: /Openai/ }));
  expect(p.onProviderChange).toHaveBeenCalledWith("openai");
  rerender(
    <ChatModelLibrary
      {...p}
      providerId="openai"
      credentialForm={<button>Add provider key</button>}
    />,
  );
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.getByPlaceholderText("Search models…")).toHaveValue("");
  expect(screen.queryByRole("button", { name: "Add provider key" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "Key" }));
  expect(screen.getByRole("button", { name: "Add provider key" })).toBeVisible();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});

it("keeps existing key selection in its own keyboard-accessible tab", async () => {
  const user = userEvent.setup();
  render(<ChatModelLibrary {...props()} credentialPicker={<button>Choose stored key</button>} />);
  expect(screen.queryByRole("button", { name: "Choose stored key" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "Models" }));
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
      profiles={[saved, { ...saved, id: "saved-custom", model: "other/custom", label: "Custom" }]}
    />,
  );
  const model = screen.getByRole("option", { name: /Claude/ });
  expect(within(model).getByLabelText("Selected")).toBeInTheDocument();
  await userEvent.click(model);
  expect(p.onModelChange).toHaveBeenCalledWith(saved.model);
  expect(screen.getByRole("option", { name: "Custom" })).toBeVisible();

  expect(screen.queryByRole("tab", { name: "Saved models" })).not.toBeInTheDocument();
});

it("shows familiar subscriptions before API keys and lists custom gateways immediately", async () => {
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
  expect(screen.getByText("Advanced / custom endpoint")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Custom gateway" }));
  expect(p.onProviderChange).toHaveBeenCalledWith("cliproxyapi");
});

it("shows the complete catalog and places the selected model first", async () => {
  const p = props();
  const models = Array.from({ length: 150 }, (_, i) => ({
    id: `vendor/model-${i}`,
    name: `Model ${i}`,
  }));
  render(<ChatModelLibrary {...p} models={models} model="vendor/model-149" catalogSource="live" />);
  const rows = screen.getAllByRole("option");
  expect(rows).toHaveLength(150);
  expect(rows[0]).toHaveTextContent("Model 149");
  expect(screen.getByText("150 models")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Models" })).toHaveAccessibleDescription(
    "150 models · Provider catalog",
  );
  await userEvent.click(screen.getByRole("option", { name: "Model 140" }));
  expect(p.onModelChange).toHaveBeenCalledWith("vendor/model-140");
  await userEvent.click(screen.getByRole("button", { name: "Search models…" }));
  await userEvent.type(screen.getByRole("combobox"), "Model 149");
  expect(screen.getAllByRole("option")).toHaveLength(1);
  expect(screen.getByText("1 model")).toBeInTheDocument();
});

it("identifies a limited fallback and exposes retry after a failed refresh", async () => {
  const refresh = vi.fn();
  const { rerender } = render(
    <ChatModelLibrary {...props()} catalogSource="curated" onRefresh={refresh} />,
  );
  expect(screen.getByText(/Limited fallback list/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Refresh models" }));
  expect(refresh).toHaveBeenCalledOnce();
  rerender(
    <ChatModelLibrary {...props()} catalogSource="curated" onRefresh={refresh} catalogError />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("The catalog could not be refreshed");
});

it("refreshes with the keyboard without selecting a model", async () => {
  const p = props();
  const refresh = vi.fn();
  render(<ChatModelLibrary {...p} onRefresh={refresh} />);
  screen.getByRole("button", { name: "Refresh models" }).focus();
  await userEvent.keyboard("{Enter}");
  expect(refresh).toHaveBeenCalledOnce();
  expect(p.onModelChange).not.toHaveBeenCalled();
});

it("reveals the selected provider when the dialog opens", () => {
  const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
  try {
    render(<ChatModelLibrary {...props()} />);
    expect(scroll.mock.contexts).toContain(screen.getByRole("button", { name: "OpenRouter" }));
    expect(scroll).toHaveBeenCalledWith({ block: "nearest", behavior: "instant" });
  } finally {
    scroll.mockRestore();
  }
});

it("reserves the provider navigation while provider connections load", () => {
  render(<ChatModelLibrary {...props()} loadingProviders />);
  expect(screen.getByRole("status")).toHaveTextContent("Provider");
  expect(screen.queryByRole("button", { name: "OpenRouter" })).not.toBeInTheDocument();
});

it("keeps loading feedback inside the list while search and provider tabs stay available", () => {
  render(<ChatModelLibrary {...props()} loading />);
  expect(within(screen.getByRole("listbox")).getByRole("status")).toHaveTextContent(
    "Loading models",
  );
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Search models…" })).toBeVisible();
  expect(screen.getByRole("tab", { name: "Models" })).toBeVisible();
});
