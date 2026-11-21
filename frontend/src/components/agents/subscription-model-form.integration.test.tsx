import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SubscriptionModelForm } from "./subscription-model-form";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-organizations", () => ({
  useTenantId: () => "org-1",
  useTenantGuard: () => () => true,
}));
vi.mock("@/stores", () => {
  const state = { user: { id: "user-1" } };
  return {
    useAuthStore: Object.assign((selector: (value: typeof state) => unknown) => selector(state), {
      getState: () => state,
    }),
  };
});

const create = vi.fn();
let profiles: { id: string; provider: string; model: string }[] = [];
vi.mock("@/hooks", () => ({
  useModelProviders: () => ({ profiles, createProfile: { mutateAsync: create, isPending: false } }),
}));
const account = {
  name: "google.json",
  provider: "antigravity",
  disabled: false,
  unavailable: false,
  label: null,
  email: null,
  status: "active",
};
let items = [account];
let enabled = true;
let failModels = false;
const selected = vi.fn();
const pending = vi.fn();
let models = ["claude-via-google"];
function mount(initialModel?: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SubscriptionModelForm
        provider="antigravity"
        initialModel={initialModel}
        onCreated={selected}
        onPendingChange={pending}
      />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  models = ["claude-via-google"];
  vi.clearAllMocks();
  profiles = [];
  items = [account];
  enabled = true;
  failModels = false;
  create.mockResolvedValue({
    id: "new-profile",
    provider: "subscription_accounts",
    model: "claude-via-google",
  });
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.endsWith("/models")) {
      if (failModels) throw new Error("offline");
      return models;
    }
    return { enabled, items };
  });
});
async function choose() {
  const combo = await screen.findByRole("combobox", { name: "Model" });
  await waitFor(() => expect(combo).not.toBeDisabled());
  await userEvent.click(combo);
  await userEvent.click(await screen.findByRole("option", { name: "claude-via-google" }));
  await userEvent.click(screen.getByRole("button", { name: "Use this model" }));
}
it("loads the selected vendor's real account catalog and creates a keyless profile", async () => {
  mount();
  await choose();
  expect(apiClient.get).toHaveBeenCalledWith("/subscription-accounts/google.json/models");
  expect(create).toHaveBeenCalledWith({
    provider: "subscription_accounts",
    secret_id: null,
    model: "claude-via-google",
    label: "Google Antigravity · claude-via-google",
  });
  expect(selected).toHaveBeenCalledWith(expect.objectContaining({ id: "new-profile" }));
});
it("reuses a saved profile instead of creating duplicates", async () => {
  profiles = [{ id: "saved", provider: "subscription_accounts", model: "claude-via-google" }];
  mount();
  await choose();
  expect(create).not.toHaveBeenCalled();
  expect(selected).toHaveBeenCalledWith(profiles[0]);
});
it("surfaces a failed creation and lets the user retry", async () => {
  create.mockRejectedValueOnce(new Error("refused"));
  mount();
  await choose();
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(selected).not.toHaveBeenCalled();
});
it("offers inline sign-in without asking for an API key or endpoint", async () => {
  items = [];
  vi.mocked(apiClient.post).mockResolvedValue({
    url: "https://google.example/sign-in",
    state: "test",
    user_code: "GOOGLE-CODE",
  });
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Connect" }));
  expect(await screen.findByText("GOOGLE-CODE")).toBeInTheDocument();
  expect(apiClient.post).toHaveBeenCalledWith("/subscription-accounts/sign-ins", {
    provider: "antigravity",
  });
  expect(screen.queryByRole("combobox", { name: "Model" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});
it("distinguishes disabled accounts from a disconnected account", async () => {
  items = [{ ...account, unavailable: true }];
  mount();
  expect(await screen.findByRole("button", { name: "Reconnect" })).toBeInTheDocument();
  expect(apiClient.get).not.toHaveBeenCalledWith("/subscription-accounts/google.json/models");
});
it("shows gateway unavailability and catalog failures explicitly", async () => {
  enabled = false;
  const first = mount();
  expect(await screen.findByText(/not enabled on this deployment/)).toBeInTheDocument();
  first.unmount();
  enabled = true;
  failModels = true;
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
  expect(screen.queryByRole("button", { name: "Use this model" })).toBeNull();
});

it("does not replace a newer choice after the form unmounts", async () => {
  let finish: ((value: object) => void) | undefined;
  create.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = mount();
  await choose();
  view.unmount();
  finish?.({ id: "late", provider: "subscription_accounts", model: "claude-via-google" });
  await waitFor(() => expect(pending).toHaveBeenLastCalledWith(false));
  expect(selected).not.toHaveBeenCalled();
});
it("refuses a non-chat profile returned by the server", async () => {
  create.mockResolvedValueOnce({
    id: "image",
    provider: "subscription_accounts",
    model: "claude-via-google",
    chat_capable: false,
  });
  mount();
  await choose();
  expect(await screen.findByRole("alert")).toHaveTextContent("not a chat model");
  expect(selected).not.toHaveBeenCalled();
});
it("offers a retry when a just-connected account has not registered its models", async () => {
  models = [];
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
  expect(screen.getByText(/has not advertised any models/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Use this model" })).toBeDisabled();
});

it("opens on the current subscription model and emphasizes the connected status", async () => {
  mount("claude-via-google");
  const combo = await screen.findByRole("combobox", { name: "Model" });
  await waitFor(() => expect(combo).toHaveTextContent("claude-via-google"));
  expect(await screen.findByText("Connected")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add account" })).toHaveClass("h-auto");
});
