import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PersonalModelConnection } from "./personal-model-connection";
import { PersonalModelKeys } from "@/components/vault/personal-model-keys";
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
