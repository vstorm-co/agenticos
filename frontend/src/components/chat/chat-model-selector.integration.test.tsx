import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatModelHeader } from "./chat-model-header";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useChatControlsStore, chatControlScope } from "@/stores/chat-controls-store";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { Perm, type Permission } from "@/types/permissions";
import type { ModelProfile } from "@/types/providers";
import type { PublishedModel } from "@/types/agents";

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const DEFAULT_MODEL = {
  profile_id: "default",
  label: "Claude Sonnet",
  provider: "anthropic",
  model: "claude-sonnet",
};
const MODEL: ModelProfile = {
  id: "team",
  label: "Team GPT",
  provider: "openai",
  model: "gpt-5",
  secret_id: "team-key",
  params: {},
  fallback_profile_ids: [],
};
const PERSONAL = {
  ...MODEL,
  id: "personal",
  label: "Personal GPT",
  secret_id: "my-key",
  usage_scope: "personal" as const,
};
const CLAUDE = {
  ...MODEL,
  id: "claude",
  label: "Claude backup",
  provider: "anthropic",
  model: "claude-sonnet",
  secret_id: "claude-key",
};
const scope = chatControlScope("person", "org-1");
const choice = () => useChatControlsStore.getState().byScope[scope]?.modelProfileId ?? null;
const trigger = () => screen.getByRole("button", { name: /^Choose chat model:/ });

function serve(
  permissions: Permission[] = [Perm.connectionsManage],
  profiles: ModelProfile[] = [MODEL, PERSONAL, CLAUDE],
) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions")
      return { permissions: permissions.map((permission) => ({ permission, scope: "all" })) };
    if (path === "/providers/model-profiles") return { items: profiles, total: profiles.length };
    if (path === "/providers/catalog")
      return {
        items: [
          { id: "openai", name: "OpenAI" },
          { id: "anthropic", name: "Anthropic" },
        ],
      };
    if (path === "/secrets")
      return {
        items: [
          { id: "team-key", name: "Team account" },
          { id: "my-key", name: "Personal account" },
        ],
      };
    if (path === "/secrets/kinds") return { items: [] };
    throw new Error(`Unexpected GET ${path}`);
  });
}

async function mount({
  readOnly = false,
  isProcessing = false,
  home = false,
  agentModel = DEFAULT_MODEL,
}: {
  readOnly?: boolean;
  isProcessing?: boolean;
  home?: boolean;
  agentModel?: PublishedModel | null;
} = {}) {
  const onChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ChatModelHeader
        name="Workspace assistant"
        home={home}
        agentModel={agentModel}
        readOnly={readOnly}
        isProcessing={isProcessing}
        onChange={onChange}
      />
    </QueryClientProvider>,
  );
  await waitFor(() =>
    expect(client.getQueryData(qk.organizations.permissions("org-1"))).toBeDefined(),
  );
  return { client, onChange };
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: { id: "person" } as never });
  useOrgStore.setState({ activeOrgId: "org-1" });
  useChatControlsStore.setState({ byScope: {} });
  serve();
});

describe("the chat header's saved model selector", () => {
  it("filters providers and accounts, searches by model or account, and saves exactly the chosen profile", async () => {
    const { onChange } = await mount();
    await userEvent.click(trigger());
    await userEvent.click(screen.getByRole("button", { name: "OpenAI" }));
    await userEvent.click(await screen.findByRole("combobox", { name: "Provider account" }));
    await userEvent.click(await screen.findByRole("option", { name: "Personal account" }));
    expect(screen.queryByRole("radio", { name: "Team GPT" })).toBeNull();
    await userEvent.type(
      screen.getByRole("textbox", { name: "Search saved models or accounts…" }),
      "personal",
    );
    await userEvent.click(screen.getByRole("radio", { name: "Personal GPT" }));
    expect(choice()).toBe("personal");
    expect(onChange).toHaveBeenCalledWith("personal");
    expect(trigger()).toHaveTextContent("Personal GPT");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("returns to the agent's model and clears the saved override", async () => {
    useChatControlsStore.getState().update(scope, { modelProfileId: "team" });
    const { onChange } = await mount();
    await userEvent.click(trigger());
    expect(screen.getByRole("radio", { name: "Team GPT" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("button", { name: /Use agent's model/ }));
    expect(choice()).toBeNull();
    expect(onChange).toHaveBeenCalledWith(null);
    expect(trigger()).toHaveTextContent("Claude Sonnet");
  });

  it("shows the current model without mutation or vault controls when permission is absent", async () => {
    serve([Perm.agentsView, Perm.agentsRun]);
    await mount();
    expect(screen.getByText("Claude Sonnet")).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Choose chat model:/ })).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalledWith("/secrets");
  });

  it("keeps a read-only conversation's model visible even for a connection manager", async () => {
    await mount({ readOnly: true });
    expect(screen.getByText("Claude Sonnet")).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("marks a deleted selection as unavailable without silently replacing it", async () => {
    useChatControlsStore.getState().update(scope, { modelProfileId: "deleted" });
    const { onChange } = await mount();
    expect(trigger()).toHaveTextContent("Model unavailable");
    expect(choice()).toBe("deleted");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("refuses disconnected and non-chat profiles but accepts a keyless local model", async () => {
    serve(
      [Perm.connectionsManage],
      [
        { ...MODEL, id: "disconnected", label: "Disconnected", missing_key: true },
        { ...MODEL, id: "speech", label: "Speech", chat_capable: false },
        {
          ...MODEL,
          id: "local",
          label: "Local",
          secret_id: null,
          base_url: "http://local.example/v1",
        },
      ],
    );
    useChatControlsStore.getState().update(scope, { modelProfileId: "disconnected" });
    const { onChange } = await mount();
    expect(within(trigger()).getByLabelText("Model unavailable")).toBeVisible();
    expect(trigger()).toHaveAccessibleName("Choose chat model: Disconnected (unavailable)");
    await userEvent.click(trigger());
    expect(screen.getByRole("radio", { name: "Disconnected" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Speech" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Disconnected" })).toHaveAccessibleDescription(
      "Connection unavailable — reconnect in Controls",
    );
    expect(screen.getByRole("radio", { name: "Speech" })).toHaveAccessibleDescription(
      "Unavailable for chat",
    );
    expect(screen.getByRole("radio", { name: "Local" })).toHaveAttribute("tabindex", "0");
    await userEvent.click(screen.getByRole("radio", { name: "Local" }));
    expect(choice()).toBe("local");
    expect(onChange).toHaveBeenCalledWith("local");
  });

  it("distinguishes a failed listing from an empty catalog and retries without clearing the choice", async () => {
    const base = vi.mocked(apiClient.get).getMockImplementation()!;
    let failed = true;
    vi.mocked(apiClient.get).mockImplementation((path: string) =>
      path === "/providers/model-profiles" && failed
        ? Promise.reject(new Error("offline"))
        : base(path),
    );
    useChatControlsStore.getState().update(scope, { modelProfileId: "team" });
    await mount();
    await userEvent.click(trigger());
    expect(await screen.findByRole("alert")).toHaveTextContent("Model settings could not be read");
    expect(screen.queryByText(/No saved models yet/)).toBeNull();
    expect(choice()).toBe("team");
    failed = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("radio", { name: "Team GPT" });
  });

  it("supports keyboard opening, choice navigation and dismissal without making a selection", async () => {
    await mount({ isProcessing: true });
    act(() => trigger().focus());
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByText(/The running turn keeps its model/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "OpenAI" }));
    const group = screen.getByRole("radiogroup", { name: "Saved models" });
    act(() => group.focus());
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getByRole("radio", { name: "Personal GPT" })).toHaveFocus();
    act(() => group.focus());
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("radio", { name: "Team GPT" })).toHaveFocus();
    act(() => screen.getByRole("radio", { name: "Team GPT" }).focus());
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("radio", { name: "Personal GPT" })).toHaveFocus();
    expect(screen.getByRole("radio", { name: "Team GPT" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: "Personal GPT" })).toHaveAttribute("tabindex", "-1");
    await userEvent.keyboard("{Home}");
    expect(screen.getByRole("radio", { name: "Team GPT" })).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getByRole("radio", { name: "Personal GPT" })).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(screen.getByRole("radio", { name: "Personal GPT" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(trigger()).toHaveFocus();
    expect(choice()).toBeNull();
  });

  it("keeps search empty states separate from having no saved models", async () => {
    await mount();
    await userEvent.click(trigger());
    await userEvent.type(
      screen.getByRole("textbox", { name: "Search saved models or accounts…" }),
      "does-not-exist",
    );
    expect(screen.getByRole("status")).toHaveTextContent("No saved models match");
    await userEvent.click(screen.getByRole("button", { name: "OpenAI" }));
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByRole("radio", { name: "Team GPT" })).toBeVisible();
  });

  it("keeps a new chat usable when neither a published default nor saved models exists", async () => {
    serve([Perm.connectionsManage], []);
    await mount({ home: true, agentModel: null });
    expect(screen.getByText("Workspace assistant")).toBeVisible();
    await userEvent.click(trigger());
    expect(screen.getByRole("status")).toHaveTextContent("No saved models yet");
    act(() => screen.getByRole("radiogroup", { name: "Saved models" }).focus());
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("radiogroup", { name: "Saved models" })).toHaveFocus();
    expect(choice()).toBeNull();
  });

  it("shows a pending saved choice before loading the provider menu", async () => {
    const base = vi.mocked(apiClient.get).getMockImplementation()!;
    let resolve!: (value: { items: ModelProfile[]; total: number }) => void;
    const pending = new Promise<{ items: ModelProfile[]; total: number }>((done) => {
      resolve = done;
    });
    vi.mocked(apiClient.get).mockImplementation((path: string) =>
      path === "/providers/model-profiles" ? pending : base(path),
    );
    useChatControlsStore.getState().update(scope, { modelProfileId: "team" });
    await mount();
    expect(trigger()).toHaveTextContent("Loading");
    await userEvent.click(trigger());
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    await act(async () => resolve({ items: [MODEL], total: 1 }));
    expect(await screen.findByRole("radio", { name: "Team GPT" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(choice()).toBe("team");
  });

  it("keeps keyless personal and endpoint accounts distinct for an uncatalogued provider", async () => {
    serve(
      [Perm.connectionsManage],
      [
        {
          ...MODEL,
          id: "subscription",
          provider: "native-provider",
          label: "Native subscription",
          secret_id: null,
          usage_scope: "personal",
        },
        {
          ...MODEL,
          id: "keyless",
          provider: "native-provider",
          label: "Keyless endpoint",
          secret_id: null,
        },
      ],
    );
    await mount();
    await userEvent.click(trigger());
    expect(screen.getByRole("button", { name: "native-provider" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Provider account" }));
    await userEvent.click(await screen.findByRole("option", { name: "Your personal account" }));
    expect(screen.queryByRole("radio", { name: "Keyless endpoint" })).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: "Native subscription" }));
    expect(choice()).toBe("subscription");
  });
});
