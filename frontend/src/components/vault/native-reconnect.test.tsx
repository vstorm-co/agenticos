import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { ConnectedAccount } from "@/types/mirage";
import { IntegrationSetupDialog } from "./integration-setup-dialog";
import { ImapSetupDialog } from "./imap-setup-dialog";
import { OdooSetupDialog } from "./odoo-setup-dialog";
import { ConnectedAccountsCard } from "./connected-accounts-card";

const { connect, application, token, imap, odoo, hook } = vi.hoisted(() => ({
  connect: vi.fn(),
  application: vi.fn(),
  token: vi.fn(),
  imap: vi.fn(),
  odoo: vi.fn(),
  hook: vi.fn(),
}));
const account: ConnectedAccount = {
  id: "selected-account",
  provider: "google",
  email: "mailbox@example.com",
  label: "Work",
  scopes: ["read"],
  owner: "personal",
  needs_reconnect: false,
  polling_failed: true,
  auth_type: "application",
  created_at: "2026-11-07T00:00:00Z",
};
vi.mock("@/hooks/use-connected-accounts", () => ({
  useConnectedAccounts: (...args: unknown[]) => hook(...args),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/en/vault" }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => false }) }));
vi.mock("@/hooks/use-secrets", () => ({
  useSecrets: () => ({
    secrets: [{ id: "new-key", name: "Replacement key", kind: "gcp_service_account" }],
    kinds: [],
    create: { isPending: false },
  }),
}));
vi.mock("@/hooks/use-integration-setup", () => ({
  useIntegrationSetup: () => ({
    error: null,
    data: {
      provider: "google",
      redirect_uri: "https://example.com/callback",
      console_url: "https://console.cloud.google.com",
      manifest_url: null,
      identity_scopes: [],
      secret_kind: "google_oauth_app",
      products: [
        {
          id: "gmail",
          name: "Gmail",
          read_scopes: ["read"],
          write_scopes: ["write"],
          application_supported: true,
          application_read_scopes: ["read"],
          application_write_scopes: ["write"],
        },
      ],
    },
  }),
}));
beforeEach(() => {
  vi.clearAllMocks();
  hook.mockReturnValue({
    accounts: [account],
    isLoading: false,
    error: null,
    disconnect: vi.fn(),
    connect,
    isConnecting: false,
    connectApplication: { mutate: application, isPending: false },
    connectToken: { mutate: token, isPending: false },
    connectImap: { mutate: imap, isPending: false },
    connectOdoo: { mutate: odoo, isPending: false },
  });
});

async function submitApplication() {
  await userEvent.click(screen.getByRole("combobox", { name: "Vault credential" }));
  await userEvent.click(screen.getByRole("option", { name: "Replacement key" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Gmail" }));
  await userEvent.click(screen.getByRole("button", { name: "Continue to account consent" }));
}

it("repairs application credentials on the selected row and keeps its authentication method", async () => {
  const close = vi.fn();
  render(
    <IntegrationSetupDialog
      owner="personal"
      provider="google"
      reconnectAccount={account}
      onClose={close}
    />,
  );
  expect(screen.getByRole("button", { name: "OAuth" })).toBeDisabled();
  expect(screen.getByLabelText("Mailbox address or Teams user directory object ID")).toHaveValue(
    account.email,
  );
  await submitApplication();
  expect(application).toHaveBeenCalledWith(
    {
      connection_id: account.id,
      provider: "google",
      secret_id: "new-key",
      subject: account.email,
      products: ["gmail"],
      write: false,
      label: "Work",
    },
    expect.any(Object),
  );
  application.mock.calls[0]?.[1].onSuccess();
  expect(close).toHaveBeenCalledOnce();
});

it.each(["00000000-0000-0000-0000-000000000001", "Automation"])(
  "prefills only a mailbox or directory ID: %s",
  (email) => {
    render(
      <IntegrationSetupDialog
        owner="personal"
        provider="google"
        reconnectAccount={{ ...account, email }}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Mailbox address or Teams user directory object ID")).toHaveValue(
      email === "Automation" ? "" : email,
    );
  },
);

it("carries the selected OAuth account through consent", async () => {
  render(
    <IntegrationSetupDialog
      owner="personal"
      provider="google"
      reconnectAccount={{ ...account, auth_type: "oauth" }}
      onClose={vi.fn()}
    />,
  );
  await userEvent.click(screen.getByRole("checkbox", { name: "Gmail" }));
  await userEvent.click(screen.getByRole("button", { name: "Continue to account consent" }));
  expect(connect).toHaveBeenCalledWith("/en/vault", {
    connection_id: account.id,
    provider: "google",
    products: ["gmail"],
    write: false,
    label: "Work",
  });
});

it("reconnects a pasted Slack token in place with its selected write ceiling", async () => {
  const close = vi.fn();
  render(
    <IntegrationSetupDialog
      owner="personal"
      provider="slack"
      reconnectAccount={{ ...account, provider: "slack", auth_type: "bearer" }}
      onClose={close}
    />,
  );
  await userEvent.type(screen.getByLabelText("Slack token"), "xoxb-new-token");
  await userEvent.click(screen.getByRole("button", { name: "Connect with token" }));
  expect(token).toHaveBeenCalledWith(
    { connection_id: account.id, token: "xoxb-new-token", label: "Work", write: false },
    expect.any(Object),
  );
  expect(screen.getByRole("button", { name: "Continue to account consent" })).toBeDisabled();
  token.mock.calls[0]?.[1].onSuccess();
  expect(close).toHaveBeenCalledOnce();
});

it("shows a poll failure, repairs that account, and clears the target before starting a new connection", async () => {
  render(<ConnectedAccountsCard owner="personal" canManage />);
  expect(screen.getByText(/Polling failed/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));
  await submitApplication();
  expect(application.mock.calls[0]?.[0].connection_id).toBe(account.id);
  await userEvent.keyboard("{Escape}");
  await userEvent.click(screen.getByRole("button", { name: "Connect Google account" }));
  expect(screen.getByRole("button", { name: "OAuth" })).toBeEnabled();
  await userEvent.click(screen.getByRole("checkbox", { name: "Gmail" }));
  await userEvent.click(screen.getByRole("button", { name: "Continue to account consent" }));
  expect(connect.mock.calls[0]?.[1]).not.toHaveProperty("connection_id");
});

it.each([false, true])(
  "validates IMAP credentials for the chosen row, reconnect=%s",
  async (reconnect) => {
    const close = vi.fn();
    render(
      <ImapSetupDialog
        owner="personal"
        reconnectAccount={reconnect ? { ...account, provider: "imap" } : undefined}
        onClose={close}
      />,
    );
    await userEvent.type(screen.getByLabelText("IMAP hostname"), "imap.example.com");
    await userEvent.clear(screen.getByLabelText("Port"));
    await userEvent.type(screen.getByLabelText("Port"), "1993");
    if (!reconnect) await userEvent.type(screen.getByLabelText("Mailbox username"), account.email);
    await userEvent.type(screen.getByLabelText("App password"), "new-password");
    await userEvent.clear(screen.getByLabelText("Mailbox folder"));
    await userEvent.type(screen.getByLabelText("Mailbox folder"), "Work");
    await userEvent.clear(screen.getByLabelText("Account label"));
    await userEvent.type(screen.getByLabelText("Account label"), "Mail");
    await userEvent.click(screen.getByRole("button", { name: "Connect account" }));
    expect(imap).toHaveBeenCalledWith(
      {
        credential: {
          host: "imap.example.com",
          port: 1993,
          username: account.email,
          password: "new-password",
          folder: "Work",
        },
        label: "Mail",
        ...(reconnect ? { connection_id: account.id } : {}),
      },
      expect.any(Object),
    );
    imap.mock.calls[0]?.[1].onSuccess();
    expect(close).toHaveBeenCalledOnce();
  },
);

it("repairs the selected Odoo database account", async () => {
  render(
    <OdooSetupDialog
      owner="personal"
      reconnectAccount={{ ...account, provider: "odoo", email: "company" }}
      onClose={vi.fn()}
    />,
  );
  expect(screen.getByLabelText("Database name")).toHaveValue("company");
  await userEvent.type(screen.getByLabelText("Odoo HTTPS origin"), "https://erp.example.com");
  await userEvent.type(screen.getByLabelText("Odoo API key"), "new-key");
  await userEvent.click(screen.getByRole("button", { name: "Connect account" }));
  expect(odoo).toHaveBeenCalledWith(
    {
      connection_id: account.id,
      credential: { origin: "https://erp.example.com", database: "company", api_key: "new-key" },
      label: "Work",
      write: false,
    },
    expect.any(Object),
  );
});
