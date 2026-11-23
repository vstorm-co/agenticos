import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ChatModelPane } from "@/components/chat/chat-model-library";
import { SubscriptionModelForm } from "./subscription-model-form";
import { apiClient } from "@/lib/api-client";
import type { SubscriptionAccount } from "@/lib/subscription-accounts-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
let tenant = "org-1";
vi.mock("@/hooks/use-organizations", () => ({
  useTenantId: () => tenant,
  useTenantGuard: () => (started: string | null) => started === tenant,
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
let profiles: { id: string; provider: string; model: string; label?: string }[] = [];
vi.mock("@/hooks", () => ({
  useModelProviders: () => ({ profiles, createProfile: { mutateAsync: create, isPending: false } }),
}));
const account: SubscriptionAccount = {
  name: "google.json",
  provider: "antigravity",
  disabled: false,
  unavailable: false,
  label: null as string | null,
  email: null as string | null,
  status: "active",
};
let items = [account];
let enabled = true;
let failModels = false;
const selected = vi.fn();
const pending = vi.fn();
const pinned = "account-" + "a".repeat(24) + "/claude-via-google";
let models = ["claude-via-google"];
function mount(initialModel?: string, library = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SubscriptionModelForm
        libraryPane={library ? ChatModelPane : undefined}
        provider="antigravity"
        initialModel={initialModel}
        onCreated={selected}
        onPendingChange={pending}
      />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  tenant = "org-1";
  models = ["claude-via-google"];
  vi.clearAllMocks();
  profiles = [];
  items = [account];
  enabled = true;
  failModels = false;
  vi.mocked(apiClient.post).mockResolvedValue({ model: pinned });
  create.mockResolvedValue({
    id: "new-profile",
    provider: "subscription_accounts",
    model: "claude-via-google",
  });
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.endsWith("/usage")) return { status: "unavailable", observed_at: null, windows: [] };
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
}
it("loads the selected vendor's real account catalog and creates a keyless profile", async () => {
  mount();
  expect(screen.queryByRole("button", { name: "Use this model" })).not.toBeInTheDocument();
  await choose();
  expect(apiClient.get).toHaveBeenCalledWith("/subscription-accounts/google.json/models");
  expect(create).toHaveBeenCalledWith({
    provider: "subscription_accounts",
    secret_id: null,
    model: pinned,
    label: `Google Antigravity · ${pinned}`,
  });
  expect(selected).toHaveBeenCalledWith(expect.objectContaining({ id: "new-profile" }));
});

it("refreshes the plain account model picker without selecting a model", async () => {
  mount();
  const picker = await screen.findByRole("combobox", { name: "Model" });
  await waitFor(() => expect(picker).toBeEnabled());
  await userEvent.click(picker);
  const before = vi
    .mocked(apiClient.get)
    .mock.calls.filter(([path]) => path === "/subscription-accounts/google.json/models").length;
  await userEvent.click(screen.getByRole("button", { name: "Refresh models" }));
  await waitFor(() =>
    expect(
      vi
        .mocked(apiClient.get)
        .mock.calls.filter(([path]) => path === "/subscription-accounts/google.json/models").length,
    ).toBeGreaterThan(before),
  );
  expect(selected).not.toHaveBeenCalled();
  expect(create).not.toHaveBeenCalled();
});
it("reuses a saved profile instead of creating duplicates", async () => {
  profiles = [{ id: "saved", provider: "subscription_accounts", model: pinned }];
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
  expect(screen.getByLabelText("Model")).toBeDisabled();
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
  expect(screen.getByRole("combobox", { name: "Model" })).toBeDisabled();
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
  expect(screen.getByRole("combobox", { name: "Model" })).toBeDisabled();
});

it("opens on the current subscription model and emphasizes the connected status", async () => {
  mount("claude-via-google");
  const combo = await screen.findByRole("combobox", { name: "Model" });
  await waitFor(() => expect(combo).toHaveTextContent("claude-via-google"));
  expect(await screen.findByText("Connected")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add account" })).toHaveClass("h-auto");
});

it("shows the connected account identity instead of only an anonymous status", async () => {
  items = [{ ...account, email: "person@example.com", label: "Personal" }];
  mount();
  expect(await screen.findByText("person@example.com")).toBeInTheDocument();
});

it("restores the chosen account and binds a selection to that account", async () => {
  const prefix = "account-" + "a".repeat(24);
  items = [
    {
      ...account,
      name: "first.json",
      email: "first@example.com",
      model_prefix: "account-" + "b".repeat(24),
    },
    { ...account, name: "second.json", email: "second@example.com", model_prefix: prefix },
  ];
  mount(pinned);
  const accounts = await screen.findByRole("combobox", { name: "Account" });
  expect(accounts).toHaveTextContent("second@example.com");
  await choose();
  expect(apiClient.post).toHaveBeenCalledWith(
    "/subscription-accounts/second.json/model-selection",
    { model: "claude-via-google" },
  );
  expect(create).toHaveBeenCalledWith(expect.objectContaining({ model: pinned }));
});

it("changes accounts before applying a model and reads only the chosen catalog", async () => {
  items = [
    { ...account, name: "first.json", email: "first@example.com" },
    { ...account, name: "second.json", email: "second@example.com" },
  ];
  mount();
  const chooser = await screen.findByRole("combobox", { name: "Account" });
  await userEvent.click(chooser);
  await userEvent.click(await screen.findByRole("option", { name: "second@example.com" }));
  expect(screen.getByRole("combobox", { name: "Model" })).toHaveTextContent("Choose a model");
  await choose();
  expect(apiClient.get).toHaveBeenCalledWith("/subscription-accounts/second.json/models");
  expect(apiClient.post).toHaveBeenCalledWith(
    "/subscription-accounts/second.json/model-selection",
    { model: "claude-via-google" },
  );
});

it("does not create a profile if account selection finishes after leaving the form", async () => {
  let finish: ((value: { model: string }) => void) | undefined;
  vi.mocked(apiClient.post).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = mount();
  await choose();
  view.unmount();
  finish?.({ model: pinned });
  await waitFor(() => expect(pending).toHaveBeenLastCalledWith(false));
  expect(create).not.toHaveBeenCalled();
  expect(selected).not.toHaveBeenCalled();
});

it("does not create a model in another organization after an account selection is in flight", async () => {
  let finish: ((value: { model: string }) => void) | undefined;
  vi.mocked(apiClient.post).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  mount();
  await choose();
  tenant = "org-2";
  finish?.({ model: pinned });
  await waitFor(() => expect(pending).toHaveBeenLastCalledWith(false));
  expect(create).not.toHaveBeenCalled();
  expect(selected).not.toHaveBeenCalled();
});

it("uses the same searchable list as API providers and moves account settings into their own tab", async () => {
  items = [{ ...account, email: "test@example.com" }];
  mount(undefined, true);
  await screen.findByRole("option", { name: "claude-via-google" });
  expect(screen.getByPlaceholderText(/Search models/)).not.toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Search models…" }));
  expect(screen.getByPlaceholderText(/Search models/)).toHaveFocus();
  expect(screen.queryByRole("combobox", { name: "Model" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Use this model" })).not.toBeInTheDocument();
  expect(screen.queryByText("Connected")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "Account" }));
  expect(await screen.findByText("Connected")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Refresh limits" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "Models" }));
  await userEvent.click(await screen.findByRole("option", { name: "claude-via-google" }));
  await waitFor(() => expect(selected).toHaveBeenCalled());
});

it("keeps saved models tied to the selected account and reports failed selections in the list", async () => {
  const prefix = "account-" + "a".repeat(24);
  items = [{ ...account, model_prefix: prefix, email: "saved@example.com" }];
  profiles = [{ id: "saved", provider: "subscription_accounts", model: pinned }];
  profiles = profiles.map((entry) => ({ ...entry, label: "Google Antigravity · " + entry.model }));
  mount(pinned, true);
  await screen.findByRole("option", { name: /claude-via-google/ });
  await userEvent.click(screen.getByRole("button", { name: "Refresh models" }));
  await waitFor(() =>
    expect(apiClient.get).toHaveBeenCalledWith("/subscription-accounts/google.json/models"),
  );
  expect(screen.queryByRole("button", { name: "saved@example.com" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "Account" }));
  expect(screen.getByRole("tab", { name: "Account" })).toHaveAttribute("aria-selected", "true");
  await userEvent.click(screen.getByRole("tab", { name: "Models" }));
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("selection refused"));
  await userEvent.click(await screen.findByRole("option"));
  expect(await screen.findByRole("alert")).toHaveTextContent("selection refused");
  expect(selected).not.toHaveBeenCalled();
});

it("offers connection setup in the library when no account is connected", async () => {
  items = [];
  mount(undefined, true);
  expect(await screen.findByRole("button", { name: "Connect" })).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Models" })).not.toBeInTheDocument();
});

it("opens direct sign-in from the branded disconnected view", async () => {
  items = [];
  vi.mocked(apiClient.post).mockResolvedValue({
    url: "https://example.test/sign-in",
    state: "signin",
    flow: "device",
    user_code: "TEST-CODE",
  });
  mount(undefined, true);
  await userEvent.click(await screen.findByRole("button", { name: "Connect" }));
  expect(await screen.findByRole("dialog")).toBeVisible();
  expect(await screen.findByText("TEST-CODE")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
it("retries account reads from the disconnected view", async () => {
  vi.mocked(apiClient.get).mockRejectedValue(new Error("offline"));
  mount(undefined, true);
  await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
  expect(apiClient.get).toHaveBeenCalledTimes(2);
});
it("withholds sign-in when subscription support is disabled", async () => {
  items = [];
  enabled = false;
  mount(undefined, true);
  await waitFor(() => expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled());
});
