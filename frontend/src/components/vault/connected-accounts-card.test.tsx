import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectedAccountsCard } from "./connected-accounts-card";

/**
 * The Google accounts a virtual terminal's folder reads as (#2191), on the vault
 * page: a row is the account's address and whether it still works, never a token.
 */

const hook = vi.fn();
vi.mock("@/components/vault/odoo-setup-dialog", () => ({
  OdooSetupDialog: ({ onClose }: { onClose: () => void }) => (
    <div role="dialog">
      <button onClick={onClose}>Close Odoo</button>
    </div>
  ),
}));
vi.mock("@/components/vault/imap-setup-dialog", () => ({
  ImapSetupDialog: ({ onClose }: { onClose: () => void }) => (
    <div role="dialog">
      <button onClick={onClose}>Close IMAP</button>
    </div>
  ),
}));
vi.mock("@/components/vault/integration-setup-dialog", () => ({
  IntegrationSetupDialog: ({ provider, onClose }: { provider: string; onClose: () => void }) => (
    <div role="dialog">
      Setup {provider}
      <button onClick={onClose}>Close setup</button>
    </div>
  ),
}));

vi.mock("@/hooks/use-connected-accounts", () => ({
  useConnectedAccounts: (...args: unknown[]) => hook(...args),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/en/vault" }));

const connect = vi.fn();
const disconnect = vi.fn();

function state(overrides: Record<string, unknown> = {}) {
  return {
    accounts: [
      {
        id: "a1",
        provider: "google",
        email: "ana@acme.com",
        scopes: ["drive", "gmail"],
        owner: "personal",
        needs_reconnect: false,
        created_at: "2026-10-22T00:00:00Z",
      },
    ],
    isLoading: false,
    error: null,
    connect,
    isConnecting: false,
    disconnect,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  hook.mockReturnValue(state());
});

describe("ConnectedAccountsCard", () => {
  it("lists an account by its address and what it was granted", () => {
    render(<ConnectedAccountsCard owner="personal" canManage />);

    expect(screen.getByText("Your connected accounts")).toBeInTheDocument();
    expect(screen.getByText("ana@acme.com")).toBeInTheDocument();
    expect(screen.getByText("2 permissions granted")).toBeInTheDocument();
    expect(hook).toHaveBeenCalledWith("personal", { provider: "google" });
  });

  it("connects another, coming back to this page", async () => {
    render(<ConnectedAccountsCard owner="organization" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Connect Google account" }));

    expect(screen.getByRole("dialog")).toHaveTextContent("Setup google");
    await userEvent.click(screen.getByRole("button", { name: "Close setup" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("asks before disconnecting, and disconnects only on yes", async () => {
    render(<ConnectedAccountsCard owner="personal" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Disconnect ana@acme.com" }));
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }));

    expect(disconnect).toHaveBeenCalledWith("a1");
  });

  it("closes the question without disconnecting", async () => {
    render(<ConnectedAccountsCard owner="personal" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Disconnect ana@acme.com" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(disconnect).not.toHaveBeenCalled();
  });

  it("says when an account's sign-in stopped working, and offers to connect it again", async () => {
    hook.mockReturnValue(state({ accounts: [{ ...state().accounts[0], needs_reconnect: true }] }));
    render(<ConnectedAccountsCard owner="personal" canManage />);

    expect(screen.getByText(/stopped working/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Setup google");
  });

  it("offers no change to somebody who may only look", () => {
    hook.mockReturnValue(state({ accounts: [{ ...state().accounts[0], needs_reconnect: true }] }));
    render(<ConnectedAccountsCard owner="organization" canManage={false} />);

    expect(screen.getByText("The organization's connected accounts")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Connect|Reconnect|Disconnect/ })).toBeNull();
  });

  it("starts the first connection from the empty state", async () => {
    hook.mockReturnValue(state({ accounts: [] }));
    render(<ConnectedAccountsCard owner="organization" canManage />);

    expect(screen.getByText(/Shared accounts can be used/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect Google account" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Setup google");
  });

  it("has nothing to offer from an empty state it may not change", () => {
    hook.mockReturnValue(state({ accounts: [] }));
    render(<ConnectedAccountsCard owner="personal" canManage={false} />);

    expect(screen.getByText(/Each person connects their own accounts/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Connect|Reconnect|Disconnect/ })).toBeNull();
  });

  it("says why the list could not be read rather than calling it empty", () => {
    hook.mockReturnValue(state({ accounts: [], error: new Error("upstream timed out") }));
    render(<ConnectedAccountsCard owner="personal" canManage />);

    expect(screen.getByText("upstream timed out")).toBeInTheDocument();
    expect(screen.queryByText("No accounts connected yet")).toBeNull();
  });
});

it("opens IMAP setup from its provider tab and closes it", async () => {
  render(<ConnectedAccountsCard owner="personal" canManage />);
  await userEvent.click(screen.getByRole("button", { name: "IMAP" }));
  expect(hook).toHaveBeenLastCalledWith("personal", { provider: "imap" });
  await userEvent.click(screen.getByRole("button", { name: "Connect IMAP account" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Close IMAP" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("opens Odoo setup from its provider tab and closes it", async () => {
  render(<ConnectedAccountsCard owner="personal" canManage />);
  await userEvent.click(screen.getByRole("button", { name: "Odoo" }));
  expect(hook).toHaveBeenLastCalledWith("personal", { provider: "odoo" });
  await userEvent.click(screen.getByRole("button", { name: "Connect Odoo account" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Close Odoo" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
