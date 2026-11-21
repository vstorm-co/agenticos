import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { CopilotModelConnection } from "./copilot-model-connection";
import { PersonalModelConnection } from "./personal-model-connection";
import { PersonalModelKeys } from "@/components/settings/personal-model-keys";
import { useAuthStore } from "@/stores";
import * as api from "@/lib/personal-model-keys-api";
import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type { AgentModelConnection } from "@/lib/personal-model-keys-api";

const tenant = vi.hoisted(() => ({ id: "org" as string | null, valid: true }));
vi.mock("@/hooks/use-organizations", () => ({
  useTenantId: () => tenant.id,
  useTenantGuard: () => () => tenant.valid,
}));
vi.mock("@/lib/personal-model-keys-api", () => ({
  agentModelConnection: vi.fn(),
  listPersonalModelKeys: vi.fn(),
  savePersonalModelKey: vi.fn(),
  deletePersonalModelKey: vi.fn(),
  startCopilotSignIn: vi.fn(),
  pollCopilotSignIn: vi.fn(),
}));
const connection: AgentModelConnection = {
  personal: true,
  connected: false,
  profile_id: "profile",
  provider: "openai",
  endpoint: "https://approved.example/v1",
  model: "shared-model",
};
function mount(children = <PersonalModelConnection agentId="agent" />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    ...render(<QueryClientProvider client={client}>{children}</QueryClientProvider>),
    client,
  };
}
beforeEach(() => {
  vi.resetAllMocks();
  tenant.id = "org";
  tenant.valid = true;
  useAuthStore.setState({
    user: {
      id: "person",
      email: "person@example.com",
      is_active: true,
      created_at: "2026-11-01T00:00:00Z",
    },
  });
  vi.mocked(api.agentModelConnection).mockResolvedValue(connection);
  vi.mocked(api.listPersonalModelKeys).mockResolvedValue({ items: [] });
});
it("connects a masked private key without giving the user a model or endpoint override", async () => {
  const user = userEvent.setup();
  vi.mocked(api.savePersonalModelKey).mockResolvedValue({ ...connection, connected: true });
  mount();
  const input = await screen.findByLabelText("Your API key");
  expect(input).toHaveAttribute("type", "password");
  expect(screen.getByText(/shared-model/)).toHaveTextContent("https://approved.example/v1");
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  await user.type(input, "secret-personal-token");
  await user.click(screen.getByRole("button", { name: "Connect key" }));
  await waitFor(() =>
    expect(api.savePersonalModelKey).toHaveBeenCalledWith(
      {
        agentId: "agent",
        api_key: "secret-personal-token",
        expected_destination: {
          profile_id: connection.profile_id,
          provider: connection.provider,
          endpoint: connection.endpoint,
          model: connection.model,
        },
      },
      expect.anything(),
    ),
  );
  await waitFor(() => expect(input).toHaveValue(""));
  expect(screen.queryByText("secret-personal-token")).not.toBeInTheDocument();
});
it("keeps a reconnect action and shows an explicit failure without claiming a saved connection", async () => {
  const user = userEvent.setup();
  vi.mocked(api.agentModelConnection).mockResolvedValue({ ...connection, connected: true });
  vi.mocked(api.savePersonalModelKey).mockRejectedValue(new Error("Connection refused"));
  mount(<PersonalModelConnection agentId="agent" manage />);
  await user.type(await screen.findByLabelText("Your API key"), "replacement");
  await user.click(screen.getByRole("button", { name: "Replace key" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Connection refused");
  expect(screen.getByRole("button", { name: "Replace key" })).toBeEnabled();
});
it("shows a failed connection lookup as an error", async () => {
  vi.mocked(api.agentModelConnection).mockRejectedValue(new Error("Lookup failed"));
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("Lookup failed");
});
it("does not ask for a personal key in organization mode", async () => {
  vi.mocked(api.agentModelConnection).mockResolvedValue({ ...connection, personal: false });
  mount();
  await waitFor(() => expect(api.agentModelConnection).toHaveBeenCalled());
  expect(screen.queryByRole("form")).not.toBeInTheDocument();
});
it("lists only personal connection metadata in Vault and removes it without organization permissions", async () => {
  const user = userEvent.setup();
  vi.mocked(api.listPersonalModelKeys).mockResolvedValue({
    items: [{ id: "mine", provider: "openai", endpoint: "" }],
  });
  vi.mocked(api.deletePersonalModelKey).mockResolvedValue(undefined);
  mount(<PersonalModelKeys />);
  expect(await screen.findByText(/Provider default/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Remove connection" }));
  await waitFor(() =>
    expect(api.deletePersonalModelKey).toHaveBeenCalledWith("mine", expect.anything()),
  );
});
it("reports a Vault lookup failure", async () => {
  vi.mocked(api.listPersonalModelKeys).mockRejectedValue(new Error("Vault lookup failed"));
  mount(<PersonalModelKeys />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Vault lookup failed");
});

it("keeps a connected key out of the conversation composer", async () => {
  vi.mocked(api.agentModelConnection).mockResolvedValue({ ...connection, connected: true });
  mount();
  await waitFor(() => expect(api.agentModelConnection).toHaveBeenCalled());
  expect(screen.queryByRole("form")).not.toBeInTheDocument();
});

it("clears the typed key when a refreshed agent points at another destination", async () => {
  const user = userEvent.setup();
  const { client } = mount();
  const input = await screen.findByLabelText("Your API key");
  await user.type(input, "original-provider-key");
  act(() =>
    client.setQueryData(qk.personalModelKeys.agent("org:person", "agent"), {
      ...connection,
      endpoint: "https://replacement.example/v1",
    }),
  );
  await waitFor(() => expect(input).toHaveValue(""));
  expect(screen.getByText(/shared-model/)).toHaveTextContent("https://replacement.example/v1");
  expect(api.savePersonalModelKey).not.toHaveBeenCalled();
});

it("refreshes a stale destination refusal and asks for a new key instead of retrying it", async () => {
  const user = userEvent.setup();
  vi.mocked(api.savePersonalModelKey).mockRejectedValue(
    new ApiError(409, "The destination changed", {
      error: { code: "PERSONAL_MODEL_DESTINATION_CHANGED", message: "The destination changed" },
    }),
  );
  mount();
  const input = await screen.findByLabelText("Your API key");
  await user.type(input, "original-provider-key");
  vi.mocked(api.agentModelConnection).mockResolvedValue({
    ...connection,
    endpoint: "https://replacement.example/v1",
  });
  await user.click(screen.getByRole("button", { name: "Connect key" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The destination changed");
  await waitFor(() => expect(input).toHaveValue(""));
  expect(screen.getByText(/shared-model/)).toHaveTextContent("https://replacement.example/v1");
  expect(api.savePersonalModelKey).toHaveBeenCalledTimes(1);
});

it("does not read another destination before a signed-in tenant or selected agent exists", async () => {
  tenant.id = null;
  useAuthStore.setState({ user: null });
  mount(<PersonalModelConnection agentId={null} />);
  expect(api.agentModelConnection).not.toHaveBeenCalled();
  expect(screen.queryByRole("form")).not.toBeInTheDocument();
});

const copilotChallenge = {
  handle: "owner-bound-sign-in-handle-which-is-not-a-token",
  user_code: "OWN-CODE",
  verification_uri: "https://github.com/login/device" as const,
  expires_at: "2026-11-18T12:15:00Z",
  poll_after_seconds: 5,
};

it("connects Copilot with a private device flow and refetches the connection", async () => {
  const copilot = { ...connection, provider: "github_copilot", endpoint: null };
  vi.mocked(api.agentModelConnection).mockResolvedValue(copilot);
  vi.mocked(api.startCopilotSignIn).mockResolvedValue(copilotChallenge);
  vi.mocked(api.pollCopilotSignIn).mockResolvedValue({
    status: "connected",
    poll_after_seconds: 0,
  });
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Sign in with GitHub" }));
  expect(await screen.findByText("OWN-CODE")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open GitHub device authorization" })).toHaveAttribute(
    "href",
    "https://github.com/login/device",
  );
  expect(api.startCopilotSignIn).toHaveBeenCalledWith("agent", {
    profile_id: "profile",
    provider: "github_copilot",
    endpoint: null,
    model: "shared-model",
  });
  vi.mocked(api.agentModelConnection).mockResolvedValue({ ...copilot, connected: true });
  await userEvent.click(screen.getByRole("button", { name: "Check authorization" }));
  await waitFor(() => expect(screen.queryByText("OWN-CODE")).not.toBeInTheDocument());
  expect(api.pollCopilotSignIn).toHaveBeenCalledWith("agent", copilotChallenge.handle);
  expect(api.savePersonalModelKey).not.toHaveBeenCalled();
});

it("keeps a pending Copilot grant out of connected state and can restart it", async () => {
  vi.mocked(api.agentModelConnection).mockResolvedValue({
    ...connection,
    provider: "github_copilot",
    endpoint: null,
  });
  vi.mocked(api.startCopilotSignIn).mockResolvedValue(copilotChallenge);
  vi.mocked(api.pollCopilotSignIn).mockResolvedValue({ status: "pending", poll_after_seconds: 12 });
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Sign in with GitHub" }));
  await userEvent.click(await screen.findByRole("button", { name: "Check authorization" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Wait 12 seconds");
  await userEvent.click(screen.getByRole("button", { name: "Start a new sign-in" }));
  await waitFor(() => expect(api.startCopilotSignIn).toHaveBeenCalledTimes(2));
});

it("reports missing Copilot application setup without an API-key fallback", async () => {
  vi.mocked(api.agentModelConnection).mockResolvedValue({
    ...connection,
    provider: "github_copilot",
    endpoint: null,
  });
  vi.mocked(api.startCopilotSignIn).mockRejectedValue(new Error("Configure the OAuth application"));
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Sign in with GitHub" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Configure the OAuth application");
  expect(api.savePersonalModelKey).not.toHaveBeenCalled();
});

it("never displays a late Copilot device code after switching tenants", async () => {
  vi.mocked(api.agentModelConnection).mockResolvedValue({
    ...connection,
    provider: "github_copilot",
    endpoint: null,
  });
  let settle: (value: typeof copilotChallenge) => void = () => undefined;
  vi.mocked(api.startCopilotSignIn).mockImplementation(
    () =>
      new Promise((resolve) => {
        settle = resolve;
      }),
  );
  const { rerender } = mount();
  await userEvent.click(await screen.findByRole("button", { name: "Sign in with GitHub" }));
  tenant.id = "other-org";
  tenant.valid = false;
  rerender(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <PersonalModelConnection agentId="agent" />
    </QueryClientProvider>,
  );
  await act(async () => settle(copilotChallenge));
  expect(screen.queryByText("OWN-CODE")).not.toBeInTheDocument();
});

it("offers explicit Copilot reconnect and can recover from a denied authorization", async () => {
  vi.mocked(api.agentModelConnection).mockResolvedValue({
    ...connection,
    provider: "github_copilot",
    endpoint: null,
    connected: true,
  });
  vi.mocked(api.startCopilotSignIn).mockResolvedValue(copilotChallenge);
  vi.mocked(api.pollCopilotSignIn).mockRejectedValue(new Error("Authorization was denied"));
  mount(<PersonalModelConnection agentId="agent" manage />);
  await userEvent.click(await screen.findByRole("button", { name: "Reconnect with GitHub" }));
  await userEvent.click(await screen.findByRole("button", { name: "Check authorization" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Authorization was denied");
  await userEvent.click(screen.getByRole("button", { name: "Start a new sign-in" }));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
});

it("ignores a late Copilot authorization result after the person signs out", async () => {
  vi.mocked(api.agentModelConnection).mockResolvedValue({
    ...connection,
    provider: "github_copilot",
    endpoint: null,
  });
  vi.mocked(api.startCopilotSignIn).mockResolvedValue(copilotChallenge);
  let settle: (value: api.CopilotSignInResult) => void = () => undefined;
  vi.mocked(api.pollCopilotSignIn).mockImplementation(
    () =>
      new Promise((resolve) => {
        settle = resolve;
      }),
  );
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Sign in with GitHub" }));
  await userEvent.click(await screen.findByRole("button", { name: "Check authorization" }));
  await act(async () => {
    useAuthStore.setState({ user: null });
  });
  await act(async () => settle({ status: "connected", poll_after_seconds: 0 }));
  expect(screen.queryByText("OWN-CODE")).not.toBeInTheDocument();
});

it.each(["tenant", "user"])(
  "requires an active %s before showing a Copilot authorization code",
  (missing) => {
    if (missing === "tenant") tenant.id = null;
    else useAuthStore.setState({ user: null });
    mount(
      <CopilotModelConnection
        agentId="agent"
        destination={{
          profile_id: "profile",
          provider: "github_copilot",
          endpoint: null,
          model: "plan-model",
        }}
        connected={false}
      />,
    );
    expect(screen.queryByRole("button", { name: "Sign in with GitHub" })).not.toBeInTheDocument();
  },
);

it("shows the provider identity when an approved model uses its default gateway", async () => {
  vi.mocked(api.agentModelConnection).mockResolvedValue({ ...connection, endpoint: null });
  mount();
  expect(await screen.findByText(/openai/)).toBeInTheDocument();
});

it("allows retrying a failed connection status read", async () => {
  vi.mocked(api.agentModelConnection).mockRejectedValueOnce(new Error("connection unavailable"));
  mount();
  expect(await screen.findByText("connection unavailable")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByLabelText("Your API key")).toBeVisible();
});
