import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectedAccountsCard } from "./connected-accounts-card";

/**
 * The Google accounts a virtual terminal's folder reads as (#2191), on the vault
 * page: a row is the account's address and whether it still works, never a token.
 */

const hook = vi.fn();
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
    expect(hook).toHaveBeenCalledWith("personal");
  });

  it("connects another, coming back to this page", async () => {
    render(<ConnectedAccountsCard owner="organization" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Connect Google account" }));

    expect(connect).toHaveBeenCalledWith("/en/vault");
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
    expect(connect).toHaveBeenCalledWith("/en/vault");
  });

  it("offers no change to somebody who may only look", () => {
    hook.mockReturnValue(state({ accounts: [{ ...state().accounts[0], needs_reconnect: true }] }));
    render(<ConnectedAccountsCard owner="organization" canManage={false} />);

    expect(screen.getByText("The organization's connected accounts")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("starts the first connection from the empty state", async () => {
    hook.mockReturnValue(state({ accounts: [] }));
    render(<ConnectedAccountsCard owner="organization" canManage />);

    expect(screen.getByText(/can read one of these for everybody/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect Google account" }));
    expect(connect).toHaveBeenCalledWith("/en/vault");
  });

  it("has nothing to offer from an empty state it may not change", () => {
    hook.mockReturnValue(state({ accounts: [] }));
    render(<ConnectedAccountsCard owner="personal" canManage={false} />);

    expect(screen.getByText(/mounts these when you talk to it/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says why the list could not be read rather than calling it empty", () => {
    hook.mockReturnValue(state({ accounts: [], error: new Error("upstream timed out") }));
    render(<ConnectedAccountsCard owner="personal" canManage />);

    expect(screen.getByText("upstream timed out")).toBeInTheDocument();
    expect(screen.queryByText("No accounts connected yet")).toBeNull();
  });
});
