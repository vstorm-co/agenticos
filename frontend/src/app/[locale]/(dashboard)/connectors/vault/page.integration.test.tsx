import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Perm, type Permission } from "@/types/permissions";
import type { ConnectedAccount } from "@/types/mirage";
import type { Secret } from "@/types/secrets";
import VaultPage from "./page";

const state = vi.hoisted(() => ({
  permissions: new Set<Permission>(),
  loading: false,
  error: null as Error | null,
  personalError: null as Error | null,
  secrets: [] as Secret[],
  personal: [] as ConnectedAccount[],
  organization: [] as ConnectedAccount[],
  connect: vi.fn(),
  disconnect: vi.fn(),
  hook: vi.fn(),
}));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: (permission: Permission) => state.permissions.has(permission) }),
  useMcpOAuthOutcome: () => {},
  useSecretPurposes: () => ({ purposes: [] }),
  useSecrets: () => ({
    secrets: state.secrets,
    kinds: [],
    isLoading: state.loading,
    listError: state.error,
    create: { mutateAsync: vi.fn(), isPending: false },
    rotate: { mutateAsync: vi.fn(), isPending: false },
    remove: { mutate: vi.fn() },
  }),
}));
vi.mock("@/hooks/use-connected-accounts", () => ({
  useConnectedAccounts: (owner: "personal" | "organization", options?: { enabled: boolean }) => {
    state.hook(owner, options);
    return {
      accounts: state[owner],
      isLoading: false,
      error: owner === "personal" ? state.personalError : null,
      isConnecting: false,
      connect: (path: string) => state.connect(owner, path),
      disconnect: (id: string) => state.disconnect(owner, id),
    };
  },
}));
vi.mock("@/components/vault/secret-dialog", () => ({
  AddSecretDialog: () => null,
  RotateSecretDialog: () => null,
}));
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  usePathname: () => "/en/vault",
}));
const account = (owner: "personal" | "organization"): ConnectedAccount => ({
  id: owner,
  owner,
  email: owner + "@example.test",
  provider: "google",
  scopes: [],
  needs_reconnect: true,
  created_at: "2026-11-01",
});

beforeEach(() => {
  vi.clearAllMocks();
  state.permissions = new Set([Perm.secretsEdit, Perm.connectionsView, Perm.mcpManage]);
  state.loading = false;
  state.error = null;
  state.personalError = null;
  state.secrets = [
    {
      id: "s1",
      name: "Main key",
      description: null,
      kind: "api_key",
      hint: "1234",
      can_edit: true,
    },
  ];
  state.personal = [account("personal")];
  state.organization = [account("organization")];
});

describe("vault inventory", () => {
  it("renders one table without separate account cards or a count strip", () => {
    render(<VaultPage />);
    expect(screen.getAllByRole("table")).toHaveLength(1);
    for (const name of ["Main key", "personal@example.test", "organization@example.test"])
      expect(screen.getByText(name)).toBeInTheDocument();
    expect(screen.queryByText("Your connected accounts")).toBeNull();
    expect(screen.queryByText(/keys stored/)).toBeNull();
  });
  it("does not list organization accounts without view access", async () => {
    state.permissions.delete(Perm.connectionsView);
    render(<VaultPage />);
    expect(state.hook).toHaveBeenCalledWith("organization", { enabled: false });
    expect(screen.queryByText("organization@example.test")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Connect account" }));
    expect(screen.queryByRole("menuitem", { name: "Organization account" })).toBeNull();
  });
  it("respects organization management authority while retaining personal actions", () => {
    state.permissions.delete(Perm.mcpManage);
    render(<VaultPage />);
    expect(
      screen.queryByRole("button", { name: "Disconnect organization@example.test" }),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Disconnect personal@example.test" })).toBeVisible();
  });
  it("connects in the selected owner scope and preserves the return route", async () => {
    render(<VaultPage />);
    await userEvent.click(screen.getByRole("button", { name: "Connect account" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Your account" }));
    expect(state.connect).toHaveBeenCalledWith("personal", "/en/vault");
  });
  it("requires confirmation before disconnecting the selected account", async () => {
    render(<VaultPage />);
    await userEvent.click(
      screen.getByRole("button", { name: "Disconnect organization@example.test" }),
    );
    expect(state.disconnect).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /^Disconnect$/ }));
    expect(state.disconnect).toHaveBeenCalledWith("organization", "organization");
  });
  it("keeps available entries visible when one account list fails", () => {
    state.personalError = new Error("Accounts unavailable");
    state.personal = [];
    render(<VaultPage />);
    expect(screen.getByText("Accounts unavailable")).toBeVisible();
    expect(screen.getByText("Main key")).toBeVisible();
    expect(screen.queryByText("No credentials yet")).toBeNull();
  });
  it("keeps table headers while loading and shows one combined empty state", () => {
    state.loading = true;
    const { rerender } = render(<VaultPage />);
    expect(screen.getByRole("table")).toHaveAttribute("aria-busy", "true");
    state.loading = false;
    state.secrets = [];
    state.personal = [];
    state.organization = [];
    rerender(<VaultPage />);
    expect(screen.getByText("No credentials yet")).toBeVisible();
  });
});
