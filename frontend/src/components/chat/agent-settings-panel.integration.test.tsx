import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatAgentSettingsPanel } from "./agent-settings-panel";
import { WorkspaceRail } from "./workspace-rail";
import { apiClient } from "@/lib/api-client";
import { announceChange } from "@/lib/live-updates";
import { qk } from "@/lib/query-keys";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import { useChatAgentSettings } from "@/hooks/use-chat-agent-settings";
import type { AgentDetail, AgentSpec, CapabilityCatalogEntry } from "@/types/agents";

vi.mock("@/lib/api-client", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client")),
  apiClient: { get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const THINKING_CAPABILITY: CapabilityCatalogEntry = {
  id: "thinking",
  name: "Reasoning",
  category: "model",
  description: "How hard the model thinks before answering.",
  side_effecting: false,
  voice: "live",
  scopes: [],
  tools: [],
  contracts: [],
  config_schema: {
    type: "object",
    properties: {
      effort: { type: "string", enum: ["low", "medium", "high"], default: "medium" },
    },
  },
  requires_secret: null,
  recommended: null,
};

function agent(id = "agent-a", changes: Partial<AgentDetail> = {}): AgentDetail {
  return {
    id,
    slug: id,
    name: id,
    description: "Original description",
    status: "published",
    visibility: "private",
    owner_user_id: "owner",
    current_version_id: "v1",
    can_run: true,
    can_edit: true,
    can_publish: false,
    draft_revision: "rev-1",
    draft_spec: {
      name: id,
      description: "Original description",
      instructions: "Answer carefully.",
      model_profile_id: "profile-a",
      model_settings: {},
      skill_ids: ["skill-1"],
      collection_ids: ["knowledge-1"],
      context_ids: [],
      mcp_servers: [],
      capabilities: [
        {
          id: "browser_use",
          config: { target: "hosted" },
          approval: "required",
          tool_approval: {},
          tool_overrides: {},
          secret_id: null,
          enabled: true,
        },
      ],
    },
    ...changes,
  };
}

let records: Record<string, AgentDetail>;
let readFailure = false;
let validateProblems = false;
let thinkingCatalogAvailable = true;

beforeEach(() => {
  vi.clearAllMocks();
  records = { "agent-a": agent(), "agent-b": agent("agent-b") };
  readFailure = false;
  validateProblems = false;
  thinkingCatalogAvailable = true;
  useBrowserPanelStore.getState().close();
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/providers/model-profiles")
      return {
        items: ["a", "b"].map((id) => ({
          id: `profile-${id}`,
          label: `Model ${id}`,
          provider: "openai",
          model: `model-${id}`,
          secret_id: "key",
          params: {},
          fallback_profile_ids: [],
        })),
        total: 2,
      };
    if (path === "/providers/catalog") return { items: [], total: 0 };
    if (path === "/agents/capabilities")
      return {
        items: thinkingCatalogAvailable ? [THINKING_CAPABILITY] : [],
        total: thinkingCatalogAvailable ? 1 : 0,
      };
    if (path.endsWith("/versions")) return { items: [{ id: "v1", version: 1 }], total: 1 };
    if (path.endsWith("/environments")) return { items: [], total: 0 };
    const match = /^\/agents\/([^/]+)$/.exec(path);
    if (match) {
      if (readFailure) throw new Error("Connection unavailable");
      return records[match[1]!];
    }
    throw new Error(`Unexpected read: ${path}`);
  });
  vi.mocked(apiClient.put).mockImplementation(async (path, body) => {
    const id = path.split("/")[2]!;
    const spec = (body as { spec: AgentSpec }).spec;
    records[id] = { ...records[id]!, draft_spec: spec, name: spec.name };
    return records[id];
  });
  vi.mocked(apiClient.post).mockImplementation(async (path) => {
    if (path.endsWith("/validate") && validateProblems) throw new Error("Draft is invalid");
    if (path.endsWith("/publish")) return { version: 2 };
    return undefined;
  });
});

function mount(overrides: Partial<React.ComponentProps<typeof ChatAgentSettingsPanel>> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const props = { agentId: "agent-a", open: true, readOnly: false, onClose: vi.fn(), ...overrides };
  const view = render(
    <QueryClientProvider client={client}>
      <ChatAgentSettingsPanel key={props.agentId} {...props} />
    </QueryClientProvider>,
  );
  return {
    ...view,
    client,
    props,
    change: (changes: Partial<typeof props>) => {
      Object.assign(props, changes);
      view.rerender(
        <QueryClientProvider client={client}>
          <ChatAgentSettingsPanel key={props.agentId} {...props} />
        </QueryClientProvider>,
      );
    },
  };
}

function mountEditor(readOnly = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderHook(() => useChatAgentSettings("agent-a", readOnly), {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

describe("agent settings beside the chat", () => {
  it("refuses changes and save requests when the editor is read-only", async () => {
    const { result } = mountEditor(true);
    await waitFor(() => expect(result.current.spec?.name).toBe("agent-a"));
    act(() => result.current.update({ name: "Refused edit" }));
    await expect(result.current.save()).resolves.toBe(false);
    expect(result.current.spec?.name).toBe("agent-a");
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("preserves the submitted draft when late controls try to edit or discard during a save", async () => {
    let finish!: (value: AgentDetail) => void;
    vi.mocked(apiClient.put).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { result } = mountEditor();
    await waitFor(() => expect(result.current.spec?.name).toBe("agent-a"));
    act(() => result.current.update({ name: "Submitted draft" }));
    let saving!: Promise<boolean>;
    act(() => {
      saving = result.current.save();
    });
    await waitFor(() => expect(result.current.saveDraft.isPending).toBe(true));
    act(() => {
      result.current.update({ name: "Late edit" });
      result.current.reset();
    });
    expect(result.current.spec?.name).toBe("Submitted draft");
    expect(apiClient.put).toHaveBeenCalledExactlyOnceWith("/agents/agent-a/draft", {
      spec: expect.objectContaining({ name: "Submitted draft" }),
      expected_revision: "rev-1",
    });
    await act(async () => {
      records["agent-a"] = {
        ...records["agent-a"]!,
        name: "Submitted draft",
        draft_spec: result.current.spec!,
      };
      finish(records["agent-a"]!);
      expect(await saving).toBe(true);
    });
    await waitFor(() => expect(result.current.dirty).toBe(false));
    expect(result.current.spec?.name).toBe("Submitted draft");
  });

  it("loads only when opened and opens settings from the workspace rail without running a tool", async () => {
    mount({ open: false });
    expect(apiClient.get).not.toHaveBeenCalled();
    render(
      <WorkspaceRail
        filesSlot={() => undefined}
        hasAgent
        panelIds={{
          browser: "browser",
          computer: "computer",
          settings: "settings",
          tasks: "tasks",
        }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Open agent settings" }));
    expect(useBrowserPanelStore.getState().surface).toBe("settings");
    expect(apiClient.post).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Open agent settings" }));
    expect(useBrowserPanelStore.getState().surface).toBeNull();
  });

  it("saves the agent draft without publishing or changing other spec bindings", async () => {
    mount();
    const input = await screen.findByRole("textbox", { name: "Name" });
    fireEvent.change(input, { target: { value: "Research assistant" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Instructions" }), {
      target: { value: "Use trusted sources." },
    });
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(screen.getByText("Draft saved · publish to apply changes")).toBeVisible(),
    );
    expect(apiClient.put).toHaveBeenCalledExactlyOnceWith("/agents/agent-a/draft", {
      spec: expect.objectContaining({
        name: "Research assistant",
        instructions: "Use trusted sources.",
        skill_ids: ["skill-1"],
        collection_ids: ["knowledge-1"],
        capabilities: [
          expect.objectContaining({ config: { target: "hosted" }, approval: "required" }),
        ],
      }),
      expected_revision: "rev-1",
    });
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("edits the default model and toggles an existing capability without losing its configuration", async () => {
    mount();
    await screen.findByRole("textbox", { name: "Name" });
    await userEvent.click(screen.getByText("Default model", { selector: "summary" }));
    await userEvent.click(await screen.findByRole("radio", { name: "Model b" }));
    await userEvent.click(screen.getByText("Tools and capabilities", { selector: "summary" }));
    await userEvent.click(screen.getByRole("switch", { name: "Web browser" }));
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(apiClient.put).toHaveBeenCalled());
    expect(records["agent-a"]!.draft_spec).toMatchObject({
      model_profile_id: "profile-b",
      capabilities: [
        {
          id: "browser_use",
          enabled: false,
          config: { target: "hosted" },
          approval: "required",
        },
      ],
    });
  });

  it("saves Thinking effort to the draft and preserves its binding when switched off", async () => {
    records["agent-a"] = agent("agent-a", {
      draft_spec: {
        ...agent("agent-a").draft_spec,
        capabilities: [
          {
            id: "browser_use",
            config: { target: "hosted" },
            approval: "required",
            tool_approval: { navigate: "never" },
            tool_overrides: {},
            secret_id: null,
            enabled: true,
          },
          {
            id: "thinking",
            config: { effort: "medium" },
            approval: "default",
            tool_approval: {},
            tool_overrides: {},
            secret_id: null,
            enabled: true,
          },
        ],
      },
    });
    mount();
    await screen.findByRole("textbox", { name: "Name" });

    const reasoning = await screen.findByRole("region", { name: "Reasoning" });
    expect(screen.getByRole("switch", { name: "Thinking" })).toBeChecked();
    await userEvent.click(within(reasoning).getByLabelText(/effort/i));
    await userEvent.click(screen.getByRole("option", { name: "high" }));
    expect(apiClient.put).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("switch", { name: "Thinking" }));
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(apiClient.put).toHaveBeenCalledTimes(1));
    expect(records["agent-a"]!.draft_spec.capabilities).toEqual([
      expect.objectContaining({
        id: "browser_use",
        config: { target: "hosted" },
        approval: "required",
        tool_approval: { navigate: "never" },
        enabled: true,
      }),
      expect.objectContaining({
        id: "thinking",
        config: { effort: "high" },
        approval: "default",
        tool_approval: {},
        enabled: false,
      }),
    ]);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("keeps Thinking's ordinary capability control when the catalog has no schema", async () => {
    thinkingCatalogAvailable = false;
    records["agent-a"] = agent("agent-a", {
      draft_spec: {
        ...agent("agent-a").draft_spec,
        capabilities: [
          {
            id: "thinking",
            config: { effort: "high" },
            approval: "default",
            tool_approval: {},
            tool_overrides: {},
            secret_id: null,
            enabled: true,
          },
        ],
      },
    });
    mount();
    await screen.findByRole("textbox", { name: "Name" });
    await userEvent.click(screen.getByText("Tools and capabilities", { selector: "summary" }));

    expect(screen.queryByRole("region", { name: "Reasoning" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Thinking" })).toBeChecked();
    await userEvent.click(screen.getByRole("switch", { name: "Thinking" }));
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(apiClient.put).toHaveBeenCalledTimes(1));
    expect(records["agent-a"]!.draft_spec.capabilities).toEqual([
      expect.objectContaining({
        id: "thinking",
        config: { effort: "high" },
        enabled: false,
      }),
    ]);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it.each([
    { can_edit: false },
    { can_edit: undefined },
    { workflow_id: "workflow" },
    { status: "archived" as const },
  ])(
    "does not render mutation controls when the resource cannot be edited: %j",
    async (changes) => {
      records["agent-a"] = agent("agent-a", changes);
      mount();
      await screen.findByText("Answer carefully.");
      expect(screen.queryByRole("textbox")).toBeNull();
      expect(screen.queryByRole("button", { name: "Save draft" })).toBeNull();
      expect(apiClient.put).not.toHaveBeenCalled();
    },
  );

  it("honors a read-only chat even when the agent grants edit access", async () => {
    mount({ readOnly: true });
    await screen.findByText("Answer carefully.");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Review and publish" })).toBeNull();
  });

  it("retains unsaved changes while collapsed or another workspace pane is open", async () => {
    const view = mount();
    fireEvent.change(await screen.findByRole("textbox", { name: "Name" }), {
      target: { value: "Keep this edit" },
    });
    view.change({ open: false });
    expect(screen.queryByRole("complementary")).toBeNull();
    view.change({ open: true });
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("Keep this edit");
    await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("agent-a");
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("keeps failed saves visibly unsaved and permits an explicit retry", async () => {
    vi.mocked(apiClient.put).mockRejectedValueOnce(new Error("Save refused"));
    mount();
    fireEvent.change(await screen.findByRole("textbox", { name: "Name" }), {
      target: { value: "Pending" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByText("Unsaved changes")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(apiClient.put).toHaveBeenCalledTimes(2);
  });

  it("does not retarget an in-flight save when the visible agent changes", async () => {
    let finish!: (value: AgentDetail) => void;
    vi.mocked(apiClient.put).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const view = mount();
    fireEvent.change(await screen.findByRole("textbox", { name: "Name" }), {
      target: { value: "Agent A change" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    view.change({ agentId: "agent-b" });
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("agent-b"),
    );
    await act(async () => finish(records["agent-a"]!));
    expect(apiClient.put).toHaveBeenCalledExactlyOnceWith(
      "/agents/agent-a/draft",
      expect.anything(),
    );
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("agent-b");
  });

  it("blocks a save after a remote edit until the conflict is resolved", async () => {
    const view = mount();
    fireEvent.change(await screen.findByRole("textbox", { name: "Name" }), {
      target: { value: "My change" },
    });
    act(() =>
      announceChange({
        organization_id: "org",
        resource: "agent",
        id: "agent-a",
        action: "updated",
        surface: "mcp",
        actor_user_id: "other",
        actor_name: "Ada",
        origin_tab: "other-tab",
      }),
    );
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
    act(() =>
      view.client.setQueryData(
        qk.agents.detail("agent-a"),
        {
          ...records["agent-a"],
          draft_spec: { ...records["agent-a"]!.draft_spec, name: "Their change" },
        },
        { updatedAt: Date.now() + 100 },
      ),
    );
    expect(await screen.findByText(/Ada/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("uses the existing validate and confirmation flow before publishing", async () => {
    records["agent-a"] = agent("agent-a", { can_publish: true });
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Review and publish" }));
    const dialog = await screen.findByRole("dialog");
    expect(apiClient.post).toHaveBeenCalledWith("/agents/agent-a/validate", {});
    expect(apiClient.post).not.toHaveBeenCalledWith("/agents/agent-a/publish", expect.anything());
    const buttons = within(dialog).getAllByRole("button");
    await userEvent.click(buttons.find((button) => button.textContent?.includes("Publish"))!);
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/agents/agent-a/publish", { note: null }),
    );
  });

  it("reports a load failure and retries without offering editable fields", async () => {
    readFailure = true;
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Agent settings could not be loaded.",
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    readFailure = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("textbox", { name: "Name" })).toHaveValue("agent-a");
  });

  it("scopes Escape to the pane and can expand without losing the draft", async () => {
    render(<textarea aria-label="Chat composer" />);
    const composer = screen.getByRole("textbox", { name: "Chat composer" });
    composer.focus();
    const view = mount();
    await screen.findByRole("textbox", { name: "Name" });
    await userEvent.click(screen.getByRole("button", { name: "Expand agent settings" }));
    expect(screen.getByRole("complementary")).toHaveAttribute("data-browser-panel", "fullscreen");
    await userEvent.click(screen.getByRole("button", { name: "Dock agent settings" }));
    composer.focus();
    fireEvent.keyDown(composer, { key: "Escape" });
    expect(view.props.onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Name" }), { key: "Escape" });
    expect(view.props.onClose).toHaveBeenCalledOnce();
    expect(composer).toHaveFocus();
  });
});
