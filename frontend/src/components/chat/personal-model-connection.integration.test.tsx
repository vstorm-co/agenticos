import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PersonalModelConnection } from "./personal-model-connection";
import { PersonalModelKeys } from "@/components/vault/personal-model-keys";
import { useAuthStore } from "@/stores";
import * as api from "@/lib/personal-model-keys-api";
import type { AgentModelConnection } from "@/lib/personal-model-keys-api";

vi.mock("@/hooks/use-organizations", () => ({
  useTenantId: () => "org",
  useTenantGuard: () => () => true,
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
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}
beforeEach(() => {
  vi.resetAllMocks();
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
      { agentId: "agent", api_key: "secret-personal-token" },
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
  mount();
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
