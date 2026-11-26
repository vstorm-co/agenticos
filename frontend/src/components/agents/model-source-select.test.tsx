import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ModelSourceSelect, modelSourceOptions } from "./model-source-select";
import { subscriptionFromChoice } from "@/lib/subscription-accounts-api";

vi.mock("@/components/vault/provider-row", () => ({
  ProviderRow: ({ name }: { name: string }) => <span>{name}</span>,
}));
const providers = [
  { id: "openrouter", label: "OpenRouter" },
  { id: "cliproxyapi", label: "CLIProxyAPI" },
  { id: "subscription_accounts", label: "Internal" },
];

it("offers individual subscriptions while preserving real provider IDs", () => {
  const options = modelSourceOptions(providers, true, (key) => key);
  expect(options[0]).toMatchObject({
    id: "subscription:claude",
    group: "subscriptions",
    mark: "anthropic",
  });
  expect(options.find((entry) => entry.id === "cliproxyapi")).toMatchObject({
    label: "modelSources.gateway",
    group: "custom",
  });
  expect(options.some((entry) => entry.id === "subscription_accounts")).toBe(false);
  expect(modelSourceOptions(providers, false, (key) => key)).toHaveLength(2);
  expect(subscriptionFromChoice("subscription:claude")).toBe("claude");
  expect(subscriptionFromChoice("openrouter")).toBeUndefined();
});

it("lists all sources immediately and supports keyboard selection", async () => {
  const change = vi.fn();
  render(
    <>
      <label htmlFor="source">Source</label>
      <ModelSourceSelect
        id="source"
        providers={providers}
        value=""
        onChange={change}
        subscriptions
      />
    </>,
  );
  const trigger = screen.getByRole("combobox", { name: "Source" });
  await userEvent.click(trigger);
  expect(screen.getByRole("option", { name: "Claude Code (Pro, Max)" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /gateway/i })).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("option", { name: "Subscription gateway (custom endpoint)" }),
  );
  expect(change).toHaveBeenCalledWith("cliproxyapi");
});

it("keeps custom gateways visible and asks for a concrete service for unknown legacy subscriptions", async () => {
  const { rerender } = render(
    <ModelSourceSelect
      id="source"
      providers={providers}
      value="cliproxyapi"
      onChange={vi.fn()}
      subscriptions={false}
    />,
  );
  expect(screen.getByRole("combobox")).toHaveTextContent("Subscription gateway (custom endpoint)");
  rerender(
    <ModelSourceSelect
      id="source"
      providers={providers}
      value="subscription_accounts"
      onChange={vi.fn()}
      subscriptions
    />,
  );
  expect(screen.getByRole("combobox")).toHaveTextContent("Choose a provider");
});
