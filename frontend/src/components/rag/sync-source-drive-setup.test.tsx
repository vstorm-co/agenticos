import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SyncSourceWizard } from "./sync-source-wizard";
import { apiClient } from "@/lib/api-client";
import { readDriveResume, saveDriveResume } from "@/lib/drive-oauth-resume";
import { useConnectedAccounts } from "@/hooks/use-connected-accounts";
import type { ConnectorInfo, SyncSourceCreate, SyncSourceRead } from "@/lib/rag-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/hooks/use-connected-accounts", () => ({ useConnectedAccounts: vi.fn() }));

/**
 * The Drive account flow end to end in the wizard: starting a consent from the
 * credential step, and coming back to it. The provider is not reached - the
 * account list and the connect call are the seam.
 */

const GDRIVE: ConnectorInfo = {
  type: "gdrive",
  name: "Google Drive",
  enabled: true,
  config_schema: {
    type: "object",
    properties: { folder_id: { type: "string", title: "Google Drive Folder ID" } },
    required: ["folder_id"],
  },
  secret_kind: "gcp_service_account",
};

const DRIVE_ACCOUNT = (
  id: string,
  email: string,
  scope = "https://www.googleapis.com/auth/drive",
) => ({
  id,
  provider: "google",
  email,
  scopes: [scope],
  owner: "organization",
  needs_reconnect: false,
  created_at: "2026-08-20T00:00:00Z",
});

const DRAFT: SyncSourceCreate = {
  name: "Engineering docs",
  connector_type: "gdrive",
  collection_name: "handbook",
  config: {},
  secret_id: null,
  connected_account_id: null,
  organizational_unit: null,
  sync_mode: "full",
  schedule_minutes: null,
};

const connect = vi.fn();

function accounts(list: ReturnType<typeof DRIVE_ACCOUNT>[], isLoading = false) {
  vi.mocked(useConnectedAccounts).mockReturnValue({
    accounts: list,
    isLoading,
    error: null,
    connect,
    isConnecting: false,
    disconnect: vi.fn(),
  } as unknown as ReturnType<typeof useConnectedAccounts>);
}

beforeEach(() => {
  window.sessionStorage.clear();
  connect.mockReset();
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/secrets") return { items: [], total: 0 };
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "builder",
        is_app_admin: false,
        permissions: ["secrets:view", "connections:view", "connections:manage"].map(
          (permission) => ({ permission, scope: "all" }),
        ),
      };
    return {};
  });
});

/** The wizard as its page holds it: the open flag is the page's, and the wizard can ask to open. */
function Page() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Add source
      </button>
      <SyncSourceWizard
        open={open}
        onOpenChange={setOpen}
        connectors={[GDRIVE]}
        collections={[{ name: "handbook", scope: "org" }]}
        defaultCollection="handbook"
        onSubmit={vi.fn()}
      />
    </>
  );
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Page />
    </QueryClientProvider>,
  );
}

describe("connecting a Google account from the wizard", () => {
  it("offers Connect Google account at once on a new Drive source, without a toggle click", async () => {
    accounts([]);
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    await userEvent.type(screen.getByLabelText("Source name"), "Engineering docs");
    await userEvent.click(screen.getByRole("button", { name: /Google Drive/ }));
    await userEvent.click(screen.getByRole("button", { name: /Continue/ }));

    const connectButton = await screen.findByRole("button", { name: "Connect Google account" });
    expect(screen.getByRole("button", { name: "Connected Google account" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await userEvent.click(connectButton);

    expect(connect).toHaveBeenCalledTimes(1);
    const saved = readDriveResume();
    expect(saved?.form.name).toBe("Engineering docs");
    expect(saved?.knownAccountIds).toEqual([]);
  });

  it("keeps the service-account choice one click away on a new Drive source", async () => {
    accounts([]);
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    await userEvent.type(screen.getByLabelText("Source name"), "Engineering docs");
    await userEvent.click(screen.getByRole("button", { name: /Google Drive/ }));
    await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Service account" }));

    expect(await screen.findByLabelText(/Vault credential/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Connect Google account" })).toBeNull();
  });
});

describe("editing a service-account Drive source", () => {
  const SERVICE_ACCOUNT_SOURCE: SyncSourceRead = {
    id: "s-1",
    organization_id: "org-1",
    name: "Engineering docs",
    connector_type: "gdrive",
    collection_name: "handbook",
    knowledge_base_id: "kb-1",
    config: { folder_id: "1AbC" },
    secret_id: "secret-1",
    secret_hint: "a1b2",
    organizational_unit: null,
    sync_mode: "full",
    schedule_minutes: null,
    is_active: true,
    last_sync_at: null,
    last_sync_status: null,
    last_error: null,
    created_at: null,
  };

  it("keeps the service-account choice when the source holds a vault credential, though accounts are visible", async () => {
    accounts([DRIVE_ACCOUNT("account-1", "docs@example.com")]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <SyncSourceWizard
          open
          onOpenChange={vi.fn()}
          connectors={[GDRIVE]}
          collections={[{ name: "handbook", scope: "org" }]}
          defaultCollection="handbook"
          editing={SERVICE_ACCOUNT_SOURCE}
          onSubmit={vi.fn()}
          onUpdate={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole("button", { name: /Continue/ }));

    expect(await screen.findByRole("button", { name: "Service account" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Connected Google account" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});

describe("coming back from a Google consent", () => {
  it("reopens on the credential step with the account the consent added chosen", async () => {
    accounts([
      DRIVE_ACCOUNT("account-1", "old@example.com"),
      DRIVE_ACCOUNT("account-2", "docs@example.com"),
    ]);
    saveDriveResume(DRAFT, ["account-1"]);
    renderPage();

    // The page remounts with the wizard closed; the snapshot reopens it.
    expect(await screen.findByRole("button", { name: /Continue/ })).toBeEnabled();
    expect(screen.queryByLabelText("Source name")).toBeNull();
    expect(readDriveResume()).toBeNull();
  });

  it("chooses a new account that was granted read-only Drive access", async () => {
    accounts([
      DRIVE_ACCOUNT(
        "account-2",
        "readonly@example.com",
        "https://www.googleapis.com/auth/drive.readonly",
      ),
    ]);
    saveDriveResume(DRAFT, []);
    renderPage();

    expect(await screen.findByRole("button", { name: /Continue/ })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Connect Google account" })).toBeNull();
  });

  it("says nothing was added when the consent returned no new account", async () => {
    accounts([]);
    saveDriveResume(DRAFT, []);
    renderPage();

    expect(await screen.findByRole("button", { name: "Connect Google account" })).toBeVisible();
    expect(screen.getByRole("button", { name: /Continue/ })).toBeDisabled();
  });
});
