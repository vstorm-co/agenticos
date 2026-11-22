import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { chatControlScope, useChatControlsStore } from "@/stores/chat-controls-store";
import { Perm } from "@/types/permissions";
import { StartModels } from "./start-models";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const PROFILE = {
  id: "personal-model",
  provider: "openrouter",
  model: "anthropic/claude-test",
  label: "Claude Test",
  secret_id: "key-one",
  params: {},
  fallback_profile_ids: [],
};
const SECRETS = [
  { id: "key-one", name: "Work account", hint: "1234", kind: "api_key", purpose: "openrouter" },
  { id: "key-two", name: "Research account", hint: "5678", kind: "api_key", purpose: "openrouter" },
];
const env = {
  canManage: true,
  catalogFails: false,
  secretsFail: false,
  modelFails: false,
  permissionFails: false,
  profilesFail: false,
  noKeys: false,
};
function serve(
  models = [
    { id: "anthropic/claude-test", name: "Claude Test" },
    ...Array.from({ length: 480 }, (_, index) => ({
      id: `vendor/model-${index}`,
      name: `Model ${index}`,
    })),
  ],
) {
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/me/permissions") {
      if (env.permissionFails) throw new Error("permissions offline");
      return {
        organization_id: "org",
        permissions: [
          Perm.agentsView,
          Perm.secretsView,
          Perm.secretsEdit,
          ...(env.canManage ? [Perm.connectionsManage] : []),
        ].map((permission) => ({ permission, scope: "all" })),
        is_app_admin: false,
        role: "operator",
      };
    }
    if (path === "/providers/catalog") {
      if (env.catalogFails) throw new Error("catalog offline");
      return {
        items: [
          { id: "openrouter", name: "OpenRouter", secret_kind: "api_key" },
          { id: "anthropic", name: "Anthropic", secret_kind: "api_key" },
          {
            id: "custom-test",
            name: "Custom endpoint",
            secret_kind: "api_key",
            requires_base_url: true,
          },
          {
            id: "subscription_accounts",
            name: "Subscriptions",
            secret_kind: "none",
            personal_gateway: true,
          },
          { id: "openai_codex", name: "Codex sign-in", secret_kind: "openai_codex" },
        ],
        total: 5,
      };
    }
    if (path === "/providers/model-profiles") {
      if (env.profilesFail) throw new Error("profiles offline");
      return { items: [PROFILE], total: 1 };
    }
    if (path === "/secrets/purposes")
      return {
        items: [
          {
            id: "openrouter",
            label: "OpenRouter",
            category: "model_provider",
            kind: "api_key",
            help_url: null,
            description: "",
          },
          {
            id: "anthropic",
            label: "Anthropic",
            category: "model_provider",
            kind: "api_key",
            help_url: null,
            description: "",
          },
          {
            id: "custom-test",
            label: "Custom endpoint",
            category: "model_provider",
            kind: "api_key",
            help_url: null,
            description: "",
          },
        ],
        total: 3,
      };
    if (path === "/secrets") {
      if (env.secretsFail) throw new Error("vault offline");
      return { items: env.noKeys ? [] : SECRETS, total: env.noKeys ? 0 : 2 };
    }
    if (path === "/secrets/kinds") return { items: [], total: 0 };
    if (path.startsWith("/providers/openrouter/models")) {
      if (env.modelFails) throw new Error("models offline");
      return {
        items: models,
        total: models.length,
        source: "live",
      };
    }
    if (path.startsWith("/providers/anthropic/models"))
      return { items: [], total: 0, source: "curated" };
    throw new Error(`Unexpected GET ${path}`);
  });
}
function mount(models?: { id: string; name: string }[]) {
  serve(models);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <StartModels />
    </QueryClientProvider>,
  );
  return client;
}
beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(env, {
    canManage: true,
    catalogFails: false,
    secretsFail: false,
    modelFails: false,
    permissionFails: false,
    profilesFail: false,
    noKeys: false,
  });
  useChatControlsStore.setState({ byScope: {} });
  useAuthStore.setState({ user: null, isAuthenticated: false });
  useOrgStore.setState({ activeOrgId: "org" });
});
it("starts with every API provider, without subscriptions, a provider rail or a model catalog", async () => {
  mount();
  expect(await screen.findByRole("button", { name: "OpenRouter" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Anthropic" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Custom endpoint" })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Subscriptions|Codex sign-in/ }),
  ).not.toBeInTheDocument();
  expect(screen.queryByPlaceholderText("Search models…")).not.toBeInTheDocument();
  expect(document.querySelector("[data-chat-model-library]")).toBeNull();
  expect(apiClient.post).not.toHaveBeenCalled();
});
it("uses a Vault account, searches the full catalog and saves only the personal chat choice", async () => {
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "OpenRouter" }));
  expect(await screen.findByText("Work account")).toBeVisible();
  expect(screen.getByPlaceholderText("Search models…")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Add a key: OpenRouter" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Browse models" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^Change/ })).toBeVisible();
  expect(await screen.findByText("481 models")).toBeVisible();
  await userEvent.type(screen.getByPlaceholderText("Search models…"), "Claude Test");
  await userEvent.click(screen.getByRole("option", { name: "Claude Test" }));
  await waitFor(() =>
    expect(
      useChatControlsStore.getState().byScope[chatControlScope(undefined, "org")]?.modelProfileId,
    ).toBe("personal-model"),
  );
  expect(apiClient.post).not.toHaveBeenCalled();
  expect(apiClient.patch).not.toHaveBeenCalled();
  expect(screen.getByText(/shared agent defaults/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "All providers" }));
  expect(screen.getByRole("button", { name: "Anthropic" })).toBeVisible();
  expect(
    useChatControlsStore.getState().byScope[chatControlScope(undefined, "org")]?.modelProfileId,
  ).toBe("personal-model");
});
it("requires a connection before browsing a provider with no key", async () => {
  env.noKeys = true;
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Anthropic" }));
  expect(await screen.findByRole("button", { name: "Add a key: Anthropic" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Browse models" })).not.toBeInTheDocument();
  expect(screen.queryByPlaceholderText("Search models…")).not.toBeInTheDocument();
});
it("lets a member choose an existing model without permission to configure connections", async () => {
  env.canManage = false;
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Claude Test" }));
  expect(
    useChatControlsStore.getState().byScope[chatControlScope(undefined, "org")]?.modelProfileId,
  ).toBe("personal-model");
  expect(screen.queryByRole("button", { name: "OpenRouter" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Add a key/ })).not.toBeInTheDocument();
  expect(apiClient.post).not.toHaveBeenCalled();
  expect(apiClient.patch).not.toHaveBeenCalled();
});

it("lets a member refresh configured models without creating or selecting one", async () => {
  env.canManage = false;
  mount();
  await screen.findByRole("button", { name: "Claude Test" });
  const before = vi
    .mocked(apiClient.get)
    .mock.calls.filter(([path]) => path === "/providers/model-profiles").length;
  await userEvent.click(screen.getByRole("button", { name: "Refresh models" }));
  await waitFor(() =>
    expect(
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === "/providers/model-profiles")
        .length,
    ).toBeGreaterThan(before),
  );
  expect(apiClient.post).not.toHaveBeenCalled();
  expect(
    useChatControlsStore.getState().byScope[chatControlScope(undefined, "org")]?.modelProfileId,
  ).toBeUndefined();
});
it("distinguishes a failed provider catalog from an empty deployment and retries", async () => {
  env.catalogFails = true;
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("We could not load");
  env.catalogFails = false;
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("button", { name: "OpenRouter" })).toBeVisible();
});
it("keeps a failed Vault read visible and does not allow model selection", async () => {
  env.secretsFail = true;
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "OpenRouter" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Model settings could not be read");
  expect(screen.queryByRole("button", { name: "Browse models" })).not.toBeInTheDocument();
  expect(apiClient.post).not.toHaveBeenCalled();
});

it("creates a model on the specifically selected Vault account", async () => {
  mount([
    { id: "anthropic/claude-test", name: "Claude Test" },
    { id: "vendor/model-479", name: "Model 479" },
  ]);
  vi.mocked(apiClient.post).mockResolvedValue({
    ...PROFILE,
    id: "new-profile",
    model: "vendor/model-479",
    secret_id: "key-two",
  });
  await userEvent.click(await screen.findByRole("button", { name: "OpenRouter" }));
  await userEvent.click(await screen.findByRole("button", { name: /^Change/ }));
  await userEvent.click(screen.getByRole("combobox", { name: "Key" }));
  await userEvent.click(screen.getByRole("option", { name: /Research account/ }));
  expect(screen.getByText("Using Vault key: Research account")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Browse models" }));
  await userEvent.click(screen.getByPlaceholderText("Search models…"));
  await userEvent.paste("model-479");
  await userEvent.click(screen.getByRole("option", { name: "Model 479" }));
  await waitFor(() =>
    expect(apiClient.post).toHaveBeenCalledWith(
      "/providers/model-profiles",
      expect.objectContaining({
        provider: "openrouter",
        model: "vendor/model-479",
        secret_id: "key-two",
      }),
    ),
  );
  await waitFor(() =>
    expect(
      useChatControlsStore.getState().byScope[chatControlScope(undefined, "org")]?.modelProfileId,
    ).toBe("new-profile"),
  );
  expect(apiClient.patch).not.toHaveBeenCalled();
});
it("reports a permission read failure instead of claiming a role denial", async () => {
  env.permissionFails = true;
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("We could not load");
  expect(screen.queryByText(/permission you do not hold/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "OpenRouter" })).not.toBeInTheDocument();
});
it("reports unreadable configured models to members instead of an empty state", async () => {
  env.canManage = false;
  env.profilesFail = true;
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("Model settings could not be read");
  expect(screen.queryByText(/No workspace models/)).not.toBeInTheDocument();
});
it("keeps catalog failures visible while allowing the user to retry the live listing", async () => {
  env.modelFails = true;
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "OpenRouter" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/catalog|models/i);
  env.modelFails = false;
  await userEvent.click(screen.getByRole("button", { name: "Refresh models" }));
  expect(await screen.findByText("481 models")).toBeVisible();
});

it("keeps account editing separate from back navigation and returns to the full catalog", async () => {
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "OpenRouter" }));
  expect(await screen.findByPlaceholderText("Search models…")).toBeVisible();
  expect(screen.getAllByRole("button", { name: "All providers" })).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: /^Change/ }));
  expect(screen.queryByPlaceholderText("Search models…")).not.toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Key" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Add a key: OpenRouter" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Browse models" }));
  expect(await screen.findByText("481 models")).toBeVisible();
  expect(screen.queryByRole("combobox", { name: "Key" })).not.toBeInTheDocument();
});

it("returns the wizard viewport to the top only on provider or account-stage changes", async () => {
  serve();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <div data-start-content>
        <StartModels />
      </div>
    </QueryClientProvider>,
  );
  const viewport = view.container.querySelector<HTMLElement>("[data-start-content]")!;
  viewport.scrollTop = 800;
  await userEvent.click(await screen.findByRole("button", { name: "OpenRouter" }));
  expect(viewport.scrollTop).toBe(0);
  await screen.findByPlaceholderText("Search models…");
  viewport.scrollTop = 400;
  await userEvent.type(screen.getByPlaceholderText("Search models…"), "Claude");
  expect(viewport.scrollTop).toBe(400);
  await userEvent.click(screen.getByRole("button", { name: /^Change/ }));
  expect(viewport.scrollTop).toBe(0);
  viewport.scrollTop = 250;
  await userEvent.click(screen.getByRole("combobox", { name: "Key" }));
  await userEvent.click(screen.getByRole("option", { name: /Research account/ }));
  expect(viewport.scrollTop).toBe(250);
  await userEvent.click(screen.getByRole("button", { name: "Browse models" }));
  expect(viewport.scrollTop).toBe(0);
  viewport.scrollTop = 500;
  await userEvent.click(screen.getByRole("button", { name: "All providers" }));
  expect(viewport.scrollTop).toBe(0);
});

it("keeps catalog status and recovery beside search before the single scrolling model list", async () => {
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "OpenRouter" }));
  const search = await screen.findByPlaceholderText("Search models…");
  const toolbar = search.closest<HTMLElement>("[data-start-catalog-toolbar]")!;
  const list = screen.getByRole("listbox");
  expect(within(toolbar).getByText("481 models")).toBeVisible();
  expect(within(toolbar).getByRole("button", { name: "Refresh models" })).toBeVisible();
  expect(within(toolbar).getByRole("combobox", { name: "Catalog region" })).toBeVisible();
  expect(toolbar.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
