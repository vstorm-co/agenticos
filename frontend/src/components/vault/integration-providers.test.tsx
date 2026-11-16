import { Dialog, DialogContent, DialogTitle } from "@/components/ui";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { IntegrationProviders, IntegrationProviderSetup } from "./integration-providers";

const state = vi.hoisted(() => ({
  canEdit: false,
  status: "missing",
  create: vi.fn(),
  error: null as Error | null,
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.canEdit }),
}));
vi.mock("@/hooks/use-integration-setup", () => ({
  useIntegrationSetup: (provider: string) => ({
    data: {
      provider,
      oauth_client_status: state.status,
      secret_kind: `${provider}_oauth_app`,
      redirect_uri: "https://console.example/callback",
      console_url: "https://console.cloud.google.com",
      identity_scopes: ["openid"],
      products: [{ read_scopes: ["read"], write_scopes: ["write"] }],
    },
    error: state.error,
  }),
}));
vi.mock("@/hooks/use-secrets", () => ({
  useSecrets: () => ({ kinds: [], create: { isPending: false, mutateAsync: state.create } }),
}));
vi.mock("./secret-dialog", () => ({
  AddSecretDialog: ({
    kind,
    onSubmit,
  }: {
    kind: string;
    onSubmit: (data: { kind: string }) => Promise<void>;
  }) => (
    <Dialog open>
      <DialogContent aria-describedby={undefined}>
        <DialogTitle>Save client</DialogTitle>
        <button onClick={() => onSubmit({ kind })}>Save client</button>
      </DialogContent>
    </Dialog>
  ),
}));
beforeEach(() => {
  state.canEdit = false;
  state.status = "missing";
  state.error = null;
  vi.clearAllMocks();
});

it("keeps provider setup out of the page until requested", async () => {
  render(<IntegrationProviders />);
  expect(screen.queryByText("Setup required")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Integrations" }));
  expect(screen.getAllByText("Setup required")).toHaveLength(3);
  expect(screen.queryByRole("button", { name: /Configure/ })).not.toBeInTheDocument();
});
it("opens organization setup for an authorized administrator", async () => {
  state.canEdit = true;
  render(<IntegrationProviders />);
  await userEvent.click(screen.getByRole("button", { name: "Integrations" }));
  await userEvent.click(screen.getByRole("button", { name: "Configure Google" }));
  expect(screen.getByText("https://console.example/callback")).toBeInTheDocument();
  expect(screen.getByText(/openid\s+read\s+write/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Save OAuth app in Vault" }));
  await userEvent.click(screen.getByRole("button", { name: "Save client" }));
  expect(state.create).toHaveBeenCalledWith({ kind: "google_oauth_app", visibility: "org" });
});
it.each(["ready", "ambiguous"])("does not create a second client when status is %s", (status) => {
  state.canEdit = true;
  state.status = status;
  render(<IntegrationProviderSetup provider="google" onClose={vi.fn()} />);
  expect(screen.queryByRole("button", { name: "Save OAuth app in Vault" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Manage credentials in Vault" })).toHaveAttribute(
    "href",
    "/vault",
  );
});
