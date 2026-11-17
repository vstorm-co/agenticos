import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IntegrationSetupDialog } from "./integration-setup-dialog";

const { setup, connect, connectToken, connectApplication, secrets } = vi.hoisted(() => ({
  setup: vi.fn(),
  connect: vi.fn(),
  connectToken: vi.fn(),
  connectApplication: vi.fn(),
  secrets: vi.fn(),
}));
vi.mock("@/hooks/use-integration-setup", () => ({ useIntegrationSetup: setup }));
vi.mock("@/hooks/use-connected-accounts", () => ({
  useConnectedAccounts: () => ({
    connect,
    isConnecting: false,
    connectToken: { mutate: connectToken, isPending: false },
    connectApplication: { mutate: connectApplication, isPending: false },
  }),
}));
vi.mock("@/hooks/use-secrets", () => ({ useSecrets: secrets }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => false }) }));
vi.mock("next/navigation", () => ({ usePathname: () => "/en/vault" }));

const info = {
  provider: "google",
  oauth_client_status: "ready",
  redirect_uri: "https://private.example/api/me/mcp-connections/oauth/callback",
  console_url: "https://console.cloud.google.com/apis/credentials",
  manifest_url: null,
  secret_kind: "google_oauth_app",
  identity_scopes: ["openid", "email"],
  enable_apis_command: "gcloud services enable gmail.googleapis.com",
  products: [
    {
      id: "gmail",
      name: "Gmail",
      read_scopes: ["gmail.readonly"],
      write_scopes: ["gmail.modify"],
      application_supported: true,
      application_read_scopes: ["gmail.readonly"],
      application_write_scopes: ["gmail.modify"],
    },
  ],
};
beforeEach(() => {
  vi.clearAllMocks();
  setup.mockReturnValue({ data: info, error: null });
  secrets.mockReturnValue({ secrets: [], kinds: [], create: { isPending: false } });
});

describe("IntegrationSetupDialog", () => {
  it("uses the server callback and requests only selected read products by default", async () => {
    render(<IntegrationSetupDialog provider="google" owner="personal" onClose={vi.fn()} />);
    expect(screen.queryByText(info.redirect_uri)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open provider console" })).not.toBeInTheDocument();
    const proceed = screen.getByRole("button", { name: "Continue to account consent" });
    expect(proceed).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "Gmail" }));
    await userEvent.click(proceed);
    expect(connect).toHaveBeenCalledWith("/en/vault", {
      provider: "google",
      products: ["gmail"],
      write: false,
      label: "",
    });
    expect(setup).toHaveBeenCalledWith("google", false);
  });

  it("requires an explicit write choice and asks for an updated provider manifest", async () => {
    render(<IntegrationSetupDialog provider="google" owner="organization" onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Gmail" }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Include write permissions/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue to account consent" }));
    expect(connect).toHaveBeenCalledWith("/en/vault", {
      provider: "google",
      products: ["gmail"],
      write: true,
      label: "",
    });
    expect(setup).toHaveBeenLastCalledWith("google", true);
  });

  it("keeps pasted tokens in a password input and sends them through the dedicated path", async () => {
    setup.mockReturnValue({
      data: { ...info, provider: "slack", manifest_url: "https://api.slack.com/apps?new_app=1" },
      error: null,
    });
    render(<IntegrationSetupDialog provider="slack" owner="personal" onClose={vi.fn()} />);
    expect(screen.queryByRole("link", { name: "Open provider console" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("Use an existing Slack user or bot token"));
    await userEvent.type(screen.getByLabelText("Slack token"), "xoxp-private");
    expect(screen.getByLabelText("Slack token")).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Connect with token" }));
    expect(connectToken).toHaveBeenCalledWith(
      { token: "xoxp-private", label: "", write: false },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
    expect(connect).not.toHaveBeenCalled();
  });

  it("does not offer an unsupported product for application access", async () => {
    setup.mockReturnValue({
      data: {
        ...info,
        products: [
          { ...info.products[0], id: "excel", name: "Excel", application_supported: false },
        ],
      },
      error: null,
    });
    render(<IntegrationSetupDialog provider="microsoft" owner="organization" onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Application access" }));
    expect(screen.getByRole("checkbox", { name: "Excel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Continue to account consent" })).toBeDisabled();
    expect(
      screen.getByLabelText("Mailbox address or Teams user directory object ID"),
    ).toBeInTheDocument();
  });
});

it("keeps the current conversation as the OAuth return and preselects its product", async () => {
  render(
    <IntegrationSetupDialog
      owner="personal"
      provider="google"
      initialProducts={["gmail"]}
      returnTo="/en/chat?conversation=existing-chat"
      onClose={vi.fn()}
    />,
  );
  expect(screen.getByRole("checkbox", { name: "Gmail" })).toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Continue to account consent" }));
  expect(connect).toHaveBeenCalledWith(
    "/en/chat?conversation=existing-chat",
    expect.objectContaining({ provider: "google", products: ["gmail"] }),
  );
});

it("blocks personal consent until an administrator registers the organization client", () => {
  setup.mockReturnValue({ data: { ...info, oauth_client_status: "missing" }, error: null });
  render(
    <IntegrationSetupDialog
      provider="google"
      owner="personal"
      initialProducts={["gmail"]}
      onClose={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Continue to account consent" })).toBeDisabled();
  expect(
    screen.getByText("Ask an administrator to configure it in Vault → Integrations."),
  ).toBeInTheDocument();
  expect(screen.queryByText(info.redirect_uri)).not.toBeInTheDocument();
  expect(secrets).toHaveBeenCalledWith({ enabled: false });
});

it("connects through AgenticOS without asking for an organization OAuth app", async () => {
  setup.mockReturnValue({
    data: { ...info, bridge_status: "ready", oauth_client_status: "missing" },
    error: null,
  });
  render(
    <IntegrationSetupDialog
      provider="google"
      owner="personal"
      initialProducts={["gmail"]}
      onClose={vi.fn()}
    />,
  );
  expect(screen.getByRole("radio", { name: /Continue with AgenticOS/ })).toBeChecked();
  expect(screen.queryByText(/Ask an administrator/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Continue to account consent" }));
  expect(connect).toHaveBeenCalledWith(
    "/en/vault",
    expect.objectContaining({ credentials_source: "agenticos", products: ["gmail"], write: false }),
  );
});

it("lets a person choose their organization app instead of the ready bridge", async () => {
  setup.mockReturnValue({ data: { ...info, bridge_status: "ready" }, error: null });
  render(
    <IntegrationSetupDialog
      provider="google"
      owner="personal"
      initialProducts={["gmail"]}
      onClose={vi.fn()}
    />,
  );
  await userEvent.click(screen.getByRole("radio", { name: /Use your own credentials/ }));
  await userEvent.click(screen.getByRole("button", { name: "Continue to account consent" }));
  expect(connect).toHaveBeenCalledWith("/en/vault", {
    provider: "google",
    products: ["gmail"],
    write: false,
    label: "",
  });
});

it("keeps managed reconnects on their original source when the bridge is unavailable", () => {
  setup.mockReturnValue({ data: { ...info, bridge_status: "unavailable" }, error: null });
  render(
    <IntegrationSetupDialog
      provider="google"
      owner="personal"
      initialProducts={["gmail"]}
      onClose={vi.fn()}
      reconnectAccount={{
        id: "managed",
        provider: "google",
        email: "user@example.com",
        owner: "personal",
        scopes: [],
        needs_reconnect: true,
        created_at: "2026-11-16",
        credentials_source: "agenticos",
      }}
    />,
  );
  expect(screen.getByRole("radio", { name: /Continue with AgenticOS/ })).toBeChecked();
  expect(screen.getByRole("radio", { name: /Use your own credentials/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Continue to account consent" })).toBeDisabled();
});
