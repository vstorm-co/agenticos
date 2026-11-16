import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { CapabilityBindingSpec } from "@/types/agents";
import type { ConnectedAccount } from "@/types/mirage";
import { NativePersonalConnections } from "./native-personal-connections";

const state = vi.hoisted(() => ({
  accounts: [] as ConnectedAccount[],
  error: null as Error | null,
  catalogError: null as Error | null,
  hook: vi.fn(),
}));
vi.mock("@/hooks/use-agents", () => ({
  useCapabilityCatalog: () => ({
    error: state.catalogError,
    capabilities: [
      { id: "gmail", name: "Gmail", config_schema: { "x-integration-provider": "google" } },
      { id: "slack", name: "Slack", config_schema: { "x-integration-provider": "slack" } },
      { id: "sandbox", name: "Sandbox", config_schema: {} },
    ],
  }),
}));
vi.mock("@/hooks/use-connected-accounts", () => ({
  useConnectedAccounts: (...args: unknown[]) => {
    state.hook(...args);
    return { accounts: state.accounts, isLoading: false, error: state.error };
  },
}));
vi.mock("@/components/vault/connected-account-setup", () => ({
  ConnectedAccountSetup: ({
    target,
    onClose,
  }: {
    target: { owner: string; provider: string; account?: ConnectedAccount; products: string[] };
    onClose: () => void;
  }) => (
    <div
      role="dialog"
      aria-label="Account setup"
      data-owner={target.owner}
      data-provider={target.provider}
      data-account={target.account?.id}
      data-products={target.products.join(",")}
    >
      <button onClick={onClose}>Close setup</button>
    </div>
  ),
}));
function binding(id = "gmail", config: Record<string, unknown> = {}): CapabilityBindingSpec {
  return {
    id,
    config,
    enabled: true,
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
  };
}
function account(id: string, changes: Partial<ConnectedAccount> = {}): ConnectedAccount {
  return {
    id,
    name: id,
    email: `${id}@example.com`,
    label: "Work",
    provider: "google",
    scopes: [],
    owner: "personal",
    needs_reconnect: false,
    created_at: "2026-11-16",
    ...changes,
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  state.accounts = [];
  state.error = null;
  state.catalogError = null;
});
it("opens personal setup for a missing product from chat", async () => {
  render(<NativePersonalConnections bindings={[binding()]} />);
  expect(screen.getByText("Not connected")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Connect" }));
  const setup = screen.getByRole("dialog", { name: "Account setup" });
  expect(setup).toHaveAttribute("data-owner", "personal");
  expect(setup).toHaveAttribute("data-provider", "google");
  expect(setup).toHaveAttribute("data-products", "gmail");
});
it("shows multiple own accounts and connects another without replacing them", async () => {
  state.accounts = [account("one"), account("two")];
  render(<NativePersonalConnections bindings={[binding()]} />);
  expect(screen.getByText("Work — one@example.com")).toBeVisible();
  expect(screen.getByText("Work — two@example.com")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Add account" }));
  expect(screen.getByRole("dialog", { name: "Account setup" })).not.toHaveAttribute("data-account");
});
it("repairs the selected account and clears it before adding a new account", async () => {
  state.accounts = [account("one"), account("two", { polling_failed: true })];
  render(<NativePersonalConnections bindings={[binding()]} />);
  await userEvent.click(screen.getByRole("button", { name: "Reconnect two@example.com" }));
  expect(screen.getByRole("dialog", { name: "Account setup" })).toHaveAttribute(
    "data-account",
    "two",
  );
  await userEvent.click(screen.getByRole("button", { name: "Close setup" }));
  await userEvent.click(screen.getByRole("button", { name: "Add account" }));
  expect(screen.getByRole("dialog", { name: "Account setup" })).not.toHaveAttribute("data-account");
});
it("honors a published account name before ambiguous labels", () => {
  state.accounts = [account("one", { label: "two" }), account("two", { label: "Selected" })];
  render(<NativePersonalConnections bindings={[binding("gmail", { account_name: "two" })]} />);
  expect(screen.queryByText("two — one@example.com")).toBeNull();
  expect(screen.getByText("Selected — two@example.com")).toBeVisible();
});
it("does not offer personal setup for organization or disabled capabilities", () => {
  const { container } = render(
    <NativePersonalConnections
      bindings={[
        binding("gmail", { account: "organization" }),
        { ...binding("slack"), enabled: false },
        binding("sandbox"),
      ]}
    />,
  );
  expect(container).toBeEmptyDOMElement();
  expect(state.hook).toHaveBeenCalledWith("personal", { provider: "all", enabled: false });
});
it("reports unreadable lists and expired accounts distinctly", () => {
  state.error = new Error("Account list unavailable");
  const { rerender } = render(<NativePersonalConnections bindings={[binding()]} />);
  expect(screen.getByText("Account list unavailable")).toBeVisible();
  expect(screen.queryByText("Not connected")).toBeNull();
  state.error = null;
  state.accounts = [account("expired", { needs_reconnect: true })];
  rerender(<NativePersonalConnections bindings={[binding()]} />);
  expect(screen.getByRole("button", { name: "Reconnect expired@example.com" })).toBeVisible();
});

it("matches a configured mailbox address without requiring a display label", () => {
  state.accounts = [account("mailbox", { label: null }), account("other")];
  render(
    <NativePersonalConnections
      bindings={[binding("gmail", { account_name: "mailbox@example.com" })]}
    />,
  );
  expect(screen.getByText("mailbox@example.com")).toBeVisible();
  expect(screen.queryByText("Work — other@example.com")).toBeNull();
});

it.each(["gmail", "sandbox"])(
  "reports an unreadable catalog for %s instead of hiding setup silently",
  (product) => {
    state.catalogError = new Error("Product catalog unavailable");
    render(<NativePersonalConnections bindings={[binding(product)]} />);
    expect(screen.getByText("Product catalog unavailable")).toBeVisible();
  },
);
