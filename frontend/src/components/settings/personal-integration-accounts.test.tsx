import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PersonalIntegrationAccounts } from "./personal-integration-accounts";
import type { ConnectedAccount } from "@/types/mirage";
const state = vi.hoisted(() => ({
  accounts: [] as ConnectedAccount[],
  hook: vi.fn(),
  disconnect: vi.fn(),
  error: null as Error | null,
  loading: false,
}));
vi.mock("@/hooks/use-connected-accounts", () => ({
  INTEGRATION_PROVIDERS: ["google", "microsoft", "slack", "imap", "odoo"],
  useConnectedAccounts: (...args: unknown[]) => {
    state.hook(...args);
    return {
      accounts: state.accounts,
      error: state.error,
      isLoading: state.loading,
      disconnect: state.disconnect,
    };
  },
}));
vi.mock("@/hooks/use-mcp-oauth-outcome", () => ({ useMcpOAuthOutcome: () => undefined }));
vi.mock("@/components/vault/connected-account-setup", () => ({
  ConnectedAccountSetup: ({
    target,
  }: {
    target: { owner: string; provider: string; products?: string[]; account?: ConnectedAccount };
  }) => (
    <div role="dialog" aria-label="Connect account" data-products={target.products?.join(",")}>
      {target.owner}:{target.provider}:{target.account?.id}
    </div>
  ),
}));
beforeEach(() => {
  vi.clearAllMocks();
  state.accounts = [];
  state.error = null;
  state.loading = false;
});
const account: ConnectedAccount = {
  id: "first",
  provider: "google",
  email: "one@example.com",
  scopes: [],
  owner: "personal",
  needs_reconnect: false,
  created_at: "2026-11-16",
};
it("connects a personal provider account from the profile", async () => {
  render(<PersonalIntegrationAccounts />);
  expect(state.hook).toHaveBeenCalledWith("personal", { provider: "all" });
  expect(screen.getByText("No accounts connected yet.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Add account" }));
  await userEvent.click(screen.getByRole("button", { name: "Gmail" }));
  expect(screen.getByRole("dialog", { name: "Connect account" })).toHaveTextContent(
    "personal:google:",
  );
  expect(screen.getByRole("dialog", { name: "Connect account" })).toHaveAttribute(
    "data-products",
    "gmail",
  );
});
it("lists several accounts and repairs exactly the chosen one", async () => {
  state.accounts = [
    account,
    { ...account, id: "second", email: "two@example.com", needs_reconnect: true },
  ];
  render(<PersonalIntegrationAccounts />);
  expect(screen.getByText("one@example.com")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Reconnect two@example.com" }));
  expect(screen.getByRole("dialog", { name: "Connect account" })).toHaveTextContent(
    "personal:google:second",
  );
});
it("requires confirmation to disconnect the selected account", async () => {
  state.accounts = [account];
  render(<PersonalIntegrationAccounts />);
  await userEvent.click(screen.getByRole("button", { name: "Disconnect one@example.com" }));
  expect(state.disconnect).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  expect(state.disconnect).toHaveBeenCalledWith("first");
});
it("shows failed loading instead of claiming that no accounts exist", () => {
  state.error = new Error("offline");
  render(<PersonalIntegrationAccounts />);
  expect(screen.queryByText("No accounts connected yet.")).not.toBeInTheDocument();
  expect(screen.getByText("offline")).toBeInTheDocument();
});
