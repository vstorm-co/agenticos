import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiKeysManager } from "./api-keys-manager";
import type { ApiKey } from "@/types/api-keys";

/**
 * Who sees what on the API keys page: the create control only with
 * `api_keys:create`, the issuer column only with `api_keys:manage`, and a revoke
 * only on a key that still works.
 */

const useApiKeysMock = vi.fn();
let held: string[] = [];

vi.mock("@/hooks", () => ({
  useApiKeys: (...args: unknown[]) => useApiKeysMock(...args),
  usePermissions: () => ({ can: (perm: string) => held.includes(perm) }),
}));

function mutation() {
  return { mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false };
}

function key(overrides: Partial<ApiKey> = {}): ApiKey {
  return {
    id: "k1",
    name: "Nightly import",
    prefix: "aos_0123abcd",
    scopes: ["collections:view", "collections:edit"],
    user_id: "u1",
    issuer_email: "ada@example.com",
    status: "active",
    expires_at: "2027-01-01T00:00:00Z",
    last_used_at: null,
    revoked_at: null,
    created_at: "2026-10-09T10:00:00Z",
    ...overrides,
  };
}

function state(overrides: Record<string, unknown> = {}) {
  return {
    keys: [key()],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    catalog: { scopes: ["agents:view"], presets: [{ id: "read_only", scopes: ["agents:view"] }] },
    create: mutation(),
    revoke: mutation(),
    ...overrides,
  };
}

describe("ApiKeysManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    held = ["api_keys:create"];
  });

  it("lists a key by its prefix, never the key, and offers to revoke it", async () => {
    const revoke = mutation();
    useApiKeysMock.mockReturnValue(state({ revoke }));
    render(<ApiKeysManager />);

    expect(screen.getByText("aos_0123abcd…")).toBeInTheDocument();
    expect(screen.getByText("2 permissions")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getAllByText("Never").length).toBeGreaterThan(0);
    expect(screen.queryByText("Issued by")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke" }));

    expect(revoke.mutateAsync).toHaveBeenCalledWith("k1");
  });

  it("revokes nothing when the confirmation is dismissed", async () => {
    const revoke = mutation();
    useApiKeysMock.mockReturnValue(state({ revoke }));
    render(<ApiKeysManager />);

    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }),
    );

    expect(revoke.mutateAsync).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("names the issuer for somebody managing every key, and offers nothing on a dead one", () => {
    held = ["api_keys:create", "api_keys:manage"];
    useApiKeysMock.mockReturnValue(
      state({
        keys: [
          key({ status: "revoked", expires_at: null, last_used_at: "2026-10-08T10:00:00Z" }),
          key({ id: "k2", status: "expired" }),
        ],
      }),
    );
    render(<ApiKeysManager />);

    expect(screen.getByText("Issued by")).toBeInTheDocument();
    expect(screen.getByText("Revoked")).toBeInTheDocument();
    expect(screen.getByText("Expired")).toBeInTheDocument();
    expect(screen.getByText("No expiry")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
  });

  it("does not draw the create control without api_keys:create", () => {
    held = [];
    useApiKeysMock.mockReturnValue(state({ catalog: null, keys: [] }));
    render(<ApiKeysManager />);

    expect(screen.queryByRole("button", { name: "Create key" })).not.toBeInTheDocument();
    expect(screen.getByText("No API keys yet")).toBeInTheDocument();
    expect(useApiKeysMock).toHaveBeenCalledWith({ canCreate: false });
  });

  it("creates a key from the dialog it opens", async () => {
    const create = mutation();
    create.mutateAsync.mockResolvedValue({ ...key(), key: "aos_0123abcdsecret" });
    useApiKeysMock.mockReturnValue(state({ create }));
    render(<ApiKeysManager />);

    await userEvent.click(screen.getByRole("button", { name: "Create key" }));
    await userEvent.type(await screen.findByLabelText("Name"), "ci");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(create.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ name: "ci", scopes: ["agents:view"] }),
    );
    expect(await screen.findByDisplayValue("aos_0123abcdsecret")).toBeInTheDocument();
  });

  it("tells a failed load apart from an empty list, and retries", async () => {
    const refetch = vi.fn();
    useApiKeysMock.mockReturnValue(state({ keys: [], error: new Error("502"), refetch }));
    render(<ApiKeysManager />);

    expect(screen.getByText("Could not load your API keys")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });
});
