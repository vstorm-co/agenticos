import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ChatModelPicker } from "./chat-model-picker";
import { apiClient } from "@/lib/api-client";
import type { ModelProfile, ProviderInfo } from "@/types/providers";
import type { SecretPurpose } from "@/types/secrets";
import { Perm } from "@/types/permissions";

vi.mock("@/lib/api-client", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client")),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const providers: ProviderInfo[] = [
  {
    id: "openai_compatible",
    name: "Custom (OpenAI-compatible)",
    secret_kind: "api_key",
    supports_base_url: true,
    requires_base_url: true,
    keyless: false,
    apis: ["chat"],
    native_api: null,
  },
  {
    id: "anthropic_compatible",
    name: "Custom (Anthropic-compatible)",
    secret_kind: "api_key",
    supports_base_url: true,
    requires_base_url: true,
    keyless: false,
    apis: [],
    native_api: null,
  },
];
const purposes: SecretPurpose[] = providers.map((provider) => ({
  id: provider.id,
  label: provider.name,
  category: "model_provider",
  kind: "api_key",
  help_url: null,
  description: "",
  icon: "",
}));
const secrets = providers.flatMap((provider) =>
  [1, 2].map((number) => ({
    id: `${provider.id}-key-${number}`,
    name: `${provider.id} key ${number}`,
    kind: "api_key",
    purpose: provider.id,
    hint: `000${number}`,
  })),
);

function saved(provider: string, id = "created"): ModelProfile {
  return {
    id,
    label: "Saved gateway model",
    provider,
    model: "gateway-model",
    base_url: "https://models.example",
    secret_id: `${provider}-key-1`,
    params: {},
    fallback_profile_ids: [],
  };
}

function serve(profiles: ModelProfile[] = []) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "owner",
        is_app_admin: false,
        permissions: [
          Perm.agentsView,
          Perm.connectionsManage,
          Perm.secretsView,
          Perm.secretsEdit,
        ].map((permission) => ({ permission, scope: "all" })),
      };
    if (path === "/providers/catalog") return { items: providers, total: providers.length };
    if (path === "/providers/model-profiles") return { items: profiles, total: profiles.length };
    if (path === "/secrets/purposes") return { items: purposes, total: purposes.length };
    if (path === "/secrets") return { items: secrets, total: secrets.length };
    if (path === "/secrets/kinds") return { items: [], total: 0 };
    if (path.startsWith("/providers/") && path.includes("/models?"))
      return {
        items: [{ id: "gateway-model", name: "Gateway model", chat_capable: true }],
        total: 1,
        source: "live",
      };
    throw new Error(`Unexpected GET ${path}`);
  });
}

async function mount(presentation: "form" | "library", provider: ProviderInfo) {
  const onChange = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ChatModelPicker
        value={null}
        agentModel={null}
        presentation={presentation}
        onChange={onChange}
      />
    </QueryClientProvider>,
  );
  if (presentation === "form") {
    await userEvent.click(await screen.findByRole("button", { name: "Change model" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
    await userEvent.click(await screen.findByRole("option", { name: provider.name }));
  } else {
    await userEvent.click(
      await screen.findByRole("button", {
        name: provider.name,
      }),
    );
  }
  await screen.findByLabelText("Endpoint");
  return onChange;
}

beforeEach(() => vi.clearAllMocks());

for (const presentation of ["form", "library"] as const) {
  for (const provider of providers) {
    it(`creates the first ${provider.id} profile through ${presentation} with explicitly confirmed endpoint and key`, async () => {
      serve();
      vi.mocked(apiClient.post).mockResolvedValue(saved(provider.id));
      const changed = await mount(presentation, provider);
      const listingCalls = () =>
        vi.mocked(apiClient.get).mock.calls.filter(([path]) => path.includes("/models?"));
      expect(listingCalls()).toHaveLength(0);
      expect(screen.queryByRole("combobox", { name: "API" })).toBeNull();
      expect(screen.queryAllByRole("combobox", { name: "Provider" })).toHaveLength(
        presentation === "form" ? 1 : 0,
      );
      await userEvent.type(screen.getByLabelText("Endpoint"), "https://models.example");
      expect(listingCalls()).toHaveLength(0);
      await userEvent.click(screen.getByRole("button", { name: "Load models" }));
      await waitFor(() => expect(listingCalls()).toHaveLength(1));
      expect(listingCalls()[0]?.[0]).toContain(`base_url=https%3A%2F%2Fmodels.example`);
      expect(listingCalls()[0]?.[0]).toContain(`secret_id=${provider.id}-key-1`);
      await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
      await userEvent.click(await screen.findByRole("option", { name: /Gateway model/ }));
      expect(changed).not.toHaveBeenCalled();
      await userEvent.click(screen.getByRole("button", { name: "Add model" }));
      await waitFor(() => expect(changed).toHaveBeenCalledWith("created"));
      expect(apiClient.post).toHaveBeenCalledWith(
        "/providers/model-profiles",
        expect.objectContaining({
          provider: provider.id,
          model: "gateway-model",
          base_url: "https://models.example",
          secret_id: `${provider.id}-key-1`,
        }),
      );
    });
  }
}

for (const presentation of ["form", "library"] as const) {
  it(`invalidates endpoint confirmation on edit in ${presentation}`, async () => {
    serve();
    await mount(presentation, providers[0]!);
    const listingCalls = () =>
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => path.includes("/models?"));
    const endpoint = screen.getByLabelText("Endpoint");
    await userEvent.type(endpoint, "https://first.example");
    await userEvent.click(screen.getByRole("button", { name: "Load models" }));
    await waitFor(() => expect(listingCalls()).toHaveLength(1));
    await userEvent.clear(endpoint);
    await userEvent.type(endpoint, "https://second.example");
    expect(listingCalls()).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Load models" }));
    await waitFor(() => expect(listingCalls()).toHaveLength(2));
    expect(listingCalls()[1]?.[0]).toContain("base_url=https%3A%2F%2Fsecond.example");
    await userEvent.click(screen.getByLabelText("Key"));
    await userEvent.click(screen.getByRole("option", { name: /openai_compatible key 2/ }));
    expect(listingCalls()).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Load models" }));
    await waitFor(() => expect(listingCalls()).toHaveLength(3));
    expect(listingCalls()[2]?.[0]).toContain("secret_id=openai_compatible-key-2");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it(`keeps the previous chat model when creation fails in ${presentation}`, async () => {
    serve();
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Gateway profile creation failed"));
    const changed = await mount(presentation, providers[0]!);
    await userEvent.type(screen.getByLabelText("Endpoint"), "https://models.example");
    await userEvent.click(screen.getByRole("button", { name: "Load models" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
    await userEvent.click(await screen.findByRole("option", { name: /Gateway model/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add model" }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    await screen.findByText("Gateway profile creation failed");
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Endpoint")).toHaveValue("https://models.example");
    expect(screen.getByRole("button", { name: "Add model" })).toBeEnabled();
  });

  it(`preserves existing models on another key in ${presentation}`, async () => {
    serve([{ ...saved("openai_compatible", "existing"), secret_id: "openai_compatible-key-2" }]);
    const changed = await mount(presentation, providers[0]!);
    expect(screen.queryByRole("tab", { name: "Saved models" })).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", {
        name: /Saved gateway model/,
      }),
    );
    expect(changed).toHaveBeenCalledWith("existing");
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.patch).not.toHaveBeenCalled();
  });
}
