import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PersonalModelConnections } from "./personal-model-connections";
import { PersonalApiConnection } from "@/components/vault/personal-api-connection";
import { ApiError } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores";
import { Perm, type Permission } from "@/types/permissions";
import type { ModelProfile } from "@/types/providers";
import type { NewSecret, Secret, SecretPurpose } from "@/types/secrets";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const USER = {
  id: "person-1",
  email: "demo@example.test",
  full_name: "Demo User",
  is_active: true,
  created_at: "2026-11-07T00:00:00Z",
};
const ANTHROPIC: SecretPurpose = {
  id: "anthropic",
  label: "Anthropic",
  category: "model_provider",
  kind: "api_key",
  help_url: "https://platform.claude.com/settings/keys",
  description: "",
  icon: "",
  personal_supported: true,
};
const OPENAI: SecretPurpose = { ...ANTHROPIC, id: "openai", label: "OpenAI", help_url: null };
const PERSONAL: Secret = {
  id: "s-personal",
  name: "My Anthropic",
  purpose: "anthropic",
  kind: "api_key",
  description: null,
  hint: "last",
  visibility: "private",
  usage_scope: "personal",
  owner_user_id: USER.id,
};
const state = {
  permissions: [] as Permission[],
  secrets: [] as Secret[],
  profiles: [] as ModelProfile[],
  readFailure: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: USER });
  state.permissions = [Perm.secretsView, Perm.secretsEdit, Perm.agentsView, Perm.connectionsManage];
  state.secrets = [];
  state.profiles = [];
  state.readFailure = false;
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/orgs") return { items: [{ id: "org-1", is_default: true }] };
    if (path === "/personal-subscriptions/claude")
      return {
        available: false,
        connected: false,
        state: "disconnected",
        login_id: null,
        authorization_url: null,
        expires_at: null,
        error_code: null,
      };
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "builder",
        is_app_admin: false,
        permissions: state.permissions.map((permission) => ({ permission, scope: "all" })),
      };
    if (path === "/secrets") {
      if (state.readFailure) throw new ApiError(503, "Connections are temporarily unavailable");
      return { items: state.secrets, total: state.secrets.length };
    }
    if (path === "/secrets/kinds") return { items: [], total: 0 };
    if (path === "/secrets/purposes") return { items: [ANTHROPIC, OPENAI], total: 2 };
    if (path === "/providers/model-profiles")
      return { items: state.profiles, total: state.profiles.length };
    if (path === "/providers/catalog")
      return {
        items: [ANTHROPIC, OPENAI].map((provider) => ({
          id: provider.id,
          name: provider.label,
          secret_kind: "api_key",
          supports_base_url: false,
          keyless: false,
          apis: [],
          native_api: null,
        })),
        total: 2,
      };
    if (
      path === "/providers/anthropic/models" ||
      path === "/providers/anthropic/models?secret_id=s-personal"
    )
      return {
        items: [{ id: "claude-test", name: "Claude test" }],
        total: 1,
        source: "curated",
      };
    throw new Error(`unexpected GET ${path}`);
  });
  vi.mocked(apiClient.post).mockImplementation(async (path, payload) => {
    if (path === "/secrets") {
      const data = payload as NewSecret;
      const secret = { ...PERSONAL, name: data.name };
      state.secrets = [...state.secrets, secret];
      return secret;
    }
    if (path === "/providers/model-profiles") {
      const data = payload as Pick<ModelProfile, "label" | "provider" | "model" | "secret_id">;
      const profile: ModelProfile = {
        ...data,
        id: "p-personal",
        usage_scope: "personal",
        params: {},
        fallback_profile_ids: [],
      };
      state.profiles = [...state.profiles, profile];
      return profile;
    }
    throw new Error(`unexpected POST ${path}`);
  });
});

afterEach(() => useAuthStore.setState({ user: null }));

async function mount(ui: ReactElement = <PersonalModelConnections />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  await waitFor(() =>
    expect(client.getQueryData(qk.organizations.permissions("current"))).toBeDefined(),
  );
  return { ...view, client };
}

describe("personal model connections", () => {
  it("withholds provider reads and connect controls without their permissions", async () => {
    state.permissions = [];
    await mount();
    expect(screen.getByText(/Viewing personal model connections needs/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /Connect API key/ })).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalledWith("/secrets");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("lists only the signed-in person's personal connections and keeps an explicit management path", async () => {
    state.permissions = [Perm.secretsView, Perm.agentsView];
    state.secrets = [
      PERSONAL,
      { ...PERSONAL, id: "s-team", name: "Team account", usage_scope: "organization" },
      { ...PERSONAL, id: "s-other", name: "Another person's account", owner_user_id: "person-2" },
    ];
    await mount();
    expect(await screen.findByText("My Anthropic")).toBeVisible();
    expect(screen.queryByText("Team account")).toBeNull();
    expect(screen.queryByText("Another person's account")).toBeNull();
    expect(screen.getByText("Saved · provider access not tested")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Connect API key|Choose model/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Manage or disconnect/ })).toHaveAttribute(
      "href",
      "/connectors/vault",
    );
  });

  it("reports an unconfigured native runtime and keeps the separate API credit option", async () => {
    await mount();
    expect(
      await screen.findByText("Claude subscription sign-in is not configured on this deployment."),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "How subscription API credits work" })).toHaveAttribute(
      "href",
      "https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers",
    );
    expect(screen.queryByRole("button", { name: /sign in|authori[sz]e|device login/i })).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("saves privately, clears the key, and waits for an explicit model choice on that exact connection", async () => {
    state.secrets = [
      { ...PERSONAL, id: "s-team", name: "Team account", usage_scope: "organization" },
    ];
    await mount();
    await userEvent.click(
      await screen.findByRole("button", { name: "Connect API key: Anthropic" }),
    );
    await userEvent.type(screen.getByLabelText("API key"), "  demo-key-value  ");
    await userEvent.click(screen.getByRole("button", { name: "Save personal connection" }));
    await screen.findByRole("heading", {
      name: "Choose a model for Anthropic · demo@example.test",
    });
    expect(apiClient.post).toHaveBeenCalledWith("/secrets", {
      name: "Anthropic · demo@example.test",
      purpose: "anthropic",
      value: { kind: "api_key", api_key: "demo-key-value" },
      visibility: "private",
      usage_scope: "personal",
    });
    expect(screen.queryByDisplayValue(/demo-key-value/)).toBeNull();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Provider")).toBeDisabled();
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith(
        "/providers/anthropic/models?secret_id=s-personal",
      ),
    );
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /Claude test/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add model" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/providers/model-profiles",
        expect.objectContaining({
          provider: "anthropic",
          model: "claude-test",
          secret_id: "s-personal",
        }),
      ),
    );
    expect(apiClient.post).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Saved Anthropic · demo@example.test · Anthropic · claude-test",
    );
  });

  it("keeps a failed save visible for retry and clears a cancelled key", async () => {
    const saved = vi.fn();
    vi.mocked(apiClient.post).mockRejectedValueOnce(
      new ApiError(409, "Choose another connection name"),
    );
    await mount(<PersonalApiConnection provider={ANTHROPIC} onCreated={saved} />);
    await userEvent.click(screen.getByRole("button", { name: "Connect API key: Anthropic" }));
    await userEvent.type(screen.getByLabelText("API key"), "failed-key");
    await userEvent.click(screen.getByRole("button", { name: "Save personal connection" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose another connection name");
    expect(saved).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Connect API key: Anthropic" }));
    expect(screen.getByLabelText("API key")).toHaveValue("");
    expect(screen.queryByRole("alert")).toBeNull();
    await userEvent.type(screen.getByLabelText("API key"), "replacement-key");
    await userEvent.click(screen.getByRole("button", { name: "Save personal connection" }));
    await waitFor(() =>
      expect(saved).toHaveBeenCalledWith(expect.objectContaining({ id: "s-personal" })),
    );
    expect(screen.queryByDisplayValue("replacement-key")).toBeNull();
  });

  it("does not turn a failed list into a claim that no connections exist", async () => {
    state.readFailure = true;
    await mount();
    expect(await screen.findByText("Connections are temporarily unavailable")).toBeVisible();
    expect(screen.queryByText(/no personal model connections/)).toBeNull();
    state.readFailure = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText(/no personal model connections/)).toBeVisible();
  });

  it("never offers the personal API form for an unsupported sign-in provider", async () => {
    await mount(
      <PersonalApiConnection
        provider={{ ...ANTHROPIC, id: "openai_codex", kind: "openai_codex" }}
        onCreated={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("refuses to collect a personal key when an older server omits the capability flag", async () => {
    await mount(
      <PersonalApiConnection
        provider={{ ...ANTHROPIC, personal_supported: undefined }}
        onCreated={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Personal connections are not enabled on this deployment yet."),
    ).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByLabelText("API key")).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it.each([
    { ...PERSONAL, usage_scope: undefined },
    { ...PERSONAL, owner_user_id: "another-person" },
  ])(
    "does not select a stored key unless the server confirms its personal scope and owner",
    async (response) => {
      vi.mocked(apiClient.post).mockResolvedValueOnce(response);
      const created = vi.fn();
      await mount(<PersonalApiConnection provider={ANTHROPIC} onCreated={created} />);
      await userEvent.click(screen.getByRole("button", { name: "Connect API key: Anthropic" }));
      await userEvent.type(screen.getByLabelText("API key"), "unconfirmed-key");
      await userEvent.click(screen.getByRole("button", { name: "Save personal connection" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The server did not confirm this connection as personal",
      );
      expect(created).not.toHaveBeenCalled();
      expect(screen.getByLabelText("API key")).toHaveValue("");
    },
  );
});
