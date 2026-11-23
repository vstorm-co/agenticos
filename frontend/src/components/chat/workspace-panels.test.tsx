import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BrowserPanel } from "./browser-panel";
import { WorkspacePanels } from "./workspace-panels";
import type { Browse } from "@/lib/browse";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useBrowserPanelStore } from "@/stores/browser-panel-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import { useChatControlsStore, saveChatControlPreferences } from "@/stores/chat-controls-store";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import { ChatScope } from "@/stores/chat-scope";

const live = vi.hoisted(() => ({ calls: [] as [string, string, boolean | undefined][] }));
vi.mock("./browser-panel", async (original) => {
  const actual = await original<typeof import("./browser-panel")>();
  return { ...actual, BrowserPanel: vi.fn(actual.BrowserPanel) };
});
vi.mock("@/hooks/use-live-browse", () => ({
  useLiveBrowse: (run: string, call: string, enabled?: boolean) => {
    live.calls.push([run, call, enabled]);
    return {
      browse: null,
      task: "",
      canControl: false,
      canRemember: false,
      status: "gone",
      send: vi.fn(),
    };
  },
}));
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), raw: vi.fn() } }));
vi.mock("@/components/chat/markdown-content", () => ({ MarkdownContent: () => null }));

const view = (callId: string, more: Partial<Browse> = {}): Browse => ({
  callId,
  runId: "actual-run",
  goal: "",
  maxSteps: null,
  url: null,
  title: null,
  steps: [],
  image: null,
  imageStep: -1,
  outcome: null,
  detail: null,
  ...more,
});
const defaults = (): ComponentProps<typeof WorkspacePanels> => ({
  teamRoom: false,
  compact: false,
  agentId: "agent",
  hostedCapabilities: ["browser_use", "computer_use"],
  canRun: true,
  agentUsesLocalTools: false,
  conversationId: "conversation",
  browses: [],
  surfaces: new Map(),
  revision: 0,
  attachments: [],
  busy: false,
  connected: true,
  readOnly: false,
  loading: false,
  onSend: vi.fn(),
  onComment: vi.fn(),
});
function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  live.calls = [];
  useAuthStore.setState({
    user: { id: "user", full_name: "User", email: "user@example.test" } as never,
  });
  useOrgStore.setState({ activeOrgId: "org" });
  useBrowserPanelStore.getState().close();
  useSourcesPanelStore.getState().close();
  useChatControlsStore.setState({ byScope: {} });
  useWorkOnStore.setState(useWorkOnStore.getInitialState(), true);
  vi.mocked(apiClient.get).mockResolvedValue({
    backend: "none",
    items: [],
    total: 0,
    bytes_total: 0,
    unreadable_reason: null,
  });
});

describe("manual workspace launchers", () => {
  it("keeps all rail controls linked to one unique target in every workspace state", async () => {
    const props = defaults();
    const test = render(<WorkspacePanels {...props} />, { wrapper });
    const controlIds = (): [string, string, string] => {
      const browser = screen.getByRole("button", { name: "Open Browser" });
      const computer = screen.getByRole("button", { name: "Open Computer" });
      const settings = screen.getByRole("button", { name: "Open agent settings" });
      const browserId = browser.getAttribute("aria-controls");
      const computerId = computer.getAttribute("aria-controls");
      const settingsId = settings.getAttribute("aria-controls");
      if (browserId === null || computerId === null || settingsId === null)
        throw new Error("Workspace controls need panel IDs");
      return [browserId, computerId, settingsId];
    };
    const expectTargets = (ids: [string, string, string]) => {
      expect(new Set(ids).size).toBe(3);
      for (const id of ids) {
        const targets = [...document.querySelectorAll("[id]")].filter(
          (element) => element.id === id,
        );
        expect(targets).toHaveLength(1);
        const target = targets.at(0);
        if (target?.hasAttribute("hidden")) {
          expect(
            target.querySelectorAll("a, button, input, select, textarea, [tabindex]"),
          ).toHaveLength(0);
        }
      }
    };

    const ids = controlIds();
    expectTargets(ids);
    expect(document.getElementById(ids[2])).toHaveAttribute("hidden");
    const settings = screen.getByRole("button", { name: "Open agent settings" });
    expect(settings).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(settings);
    expectTargets(ids);
    expect(settings).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("complementary", { name: "Agent settings" })).toHaveAttribute(
      "id",
      ids[2],
    );
    await userEvent.click(screen.getByRole("button", { name: "Close agent settings" }));
    expectTargets(ids);
    expect(settings).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById(ids[2])).toHaveAttribute("hidden");
    await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
    expectTargets(ids);
    await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
    expectTargets(ids);
    await userEvent.click(screen.getByRole("button", { name: /Show the files/ }));
    expectTargets(ids);

    test.rerender(<WorkspacePanels {...props} compact />);
    expect(screen.queryByRole("navigation", { name: "Workspace" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Open Browser" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Open Computer" })).toBeNull();
    expectTargets(ids);

    act(() => useBrowserPanelStore.getState().openSurface("browser"));
    expectTargets(ids);
    expect(screen.getByRole("complementary", { name: "Browser" })).toHaveAttribute("id", ids[0]);
    act(() => useBrowserPanelStore.getState().openSurface("computer"));
    expectTargets(ids);
    expect(screen.getByRole("complementary", { name: "Computer" })).toHaveAttribute("id", ids[1]);
  });

  it("unmounts the Tasks panel when its close button is pressed", async () => {
    vi.mocked(apiClient.get).mockImplementation((path: string) =>
      Promise.resolve(
        path === "/conversations/background-tasks"
          ? []
          : { backend: "none", items: [], total: 0, bytes_total: 0, unreadable_reason: null },
      ),
    );
    render(<WorkspacePanels {...defaults()} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: "Open tasks" }));
    expect(screen.getByRole("complementary", { name: "Tasks" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close tasks" }));
    expect(screen.queryByRole("complementary", { name: "Tasks" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open tasks" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("does not attach a personal native browser when the hosted Browser opener is used", async () => {
    const props = defaults();
    render(
      <WorkspacePanels
        {...props}
        browses={[view("native", { nativeId: "personal-browser", navigable: true })]}
      />,
      { wrapper },
    );
    await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
    expect(screen.getByRole("textbox", { name: "Website address" })).toBeVisible();
    expect(live.calls).toEqual([]);
    expect(props.onSend).not.toHaveBeenCalled();
  });
  it("keeps all openers visible and opens an idle pane without sending, provisioning, or a live socket", async () => {
    const props = defaults();
    render(<WorkspacePanels {...props} />, { wrapper });
    expect(screen.getByRole("navigation", { name: "Workspace" })).toHaveAttribute(
      "data-tour",
      "chat-workspace",
    );
    expect(screen.getByRole("button", { name: "Open Computer" })).toBeVisible();
    expect(screen.getByRole("button", { name: /Show the files/ })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
    expect(screen.getByRole("heading", { name: "Browser" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Website address" })).toHaveValue("");
    const browserId = screen
      .getByRole("button", { name: "Open Browser" })
      .getAttribute("aria-controls");
    expect(screen.getByRole("complementary", { name: "Browser" })).toHaveAttribute("id", browserId);
    expect(props.onSend).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(live.calls).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Close workspace panel" }));
    expect(screen.queryByRole("heading", { name: "Browser" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
    expect(screen.getByRole("heading", { name: "Computer" })).toBeVisible();
    expect(screen.queryByRole("textbox")).toBeNull();
    const computerId = screen
      .getByRole("button", { name: "Open Computer" })
      .getAttribute("aria-controls");
    expect(computerId).not.toBe(browserId);
    expect(screen.getByRole("complementary", { name: "Computer" })).toHaveAttribute(
      "id",
      computerId,
    );
    await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
    expect(useBrowserPanelStore.getState().surface).toBeNull();
  });

  it("hides the workspace rail in compact chats and below lg", () => {
    const props = defaults();
    const test = render(<WorkspacePanels {...props} />, { wrapper });
    expect(screen.getByRole("navigation", { name: "Workspace" })).toHaveClass("hidden", "lg:flex");

    test.rerender(<WorkspacePanels {...props} compact />);
    expect(screen.queryByRole("navigation", { name: "Workspace" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Open agent settings" })).toBeNull();
  });

  it("sends the chosen web destination only on submit and sends the hosted computer request explicitly", async () => {
    const props = defaults();
    render(<WorkspacePanels {...props} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
    await userEvent.click(screen.getByRole("button", { name: "Ask agent to open browser" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/https:/);
    expect(props.onSend).not.toHaveBeenCalled();
    await userEvent.type(
      screen.getByRole("textbox", { name: "Website address" }),
      "https://example.test/docs",
    );
    expect(screen.queryByRole("alert")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Ask agent to open browser" }));
    expect(props.onSend).toHaveBeenCalledExactlyOnceWith(
      expect.stringContaining("Open https://example.test/docs in your hosted browser"),
    );
    await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
    await userEvent.click(screen.getByRole("button", { name: "Ask agent to start computer" }));
    expect(props.onSend).toHaveBeenLastCalledWith(
      expect.stringContaining("Start your hosted computer"),
    );
    expect(useBrowserPanelStore.getState()).toMatchObject({
      surface: "computer",
      openCallId: null,
    });
  });

  it.each(["file:///tmp/private", "https://user:pass@example.test", "javascript:alert(1)"])(
    "does not send an invalid destination %s",
    async (url) => {
      const props = defaults();
      render(<WorkspacePanels {...props} />, { wrapper });
      await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
      await userEvent.type(screen.getByRole("textbox", { name: "Website address" }), url);
      await userEvent.click(screen.getByRole("button", { name: "Ask agent to open browser" }));
      expect(screen.getByRole("alert")).toBeVisible();
      expect(props.onSend).not.toHaveBeenCalled();
    },
  );

  it("resumes the saved browser session through the normal conversation send action", async () => {
    const props = defaults();
    render(
      <WorkspacePanels
        {...props}
        browses={[
          view("saved-page", {
            navigable: true,
            tabId: "saved-tab",
            title: "Docs",
            url: "https://example.test/docs",
            outcome: "done",
            resumable: true,
          }),
        ]}
      />,
      { wrapper },
    );
    await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
    expect(screen.getByRole("tab", { name: "Docs" })).toHaveAttribute("aria-selected", "true");
    expect(props.onSend).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Resume session" }));

    expect(props.onSend).toHaveBeenCalledExactlyOnceWith(
      "Resume the browser session. Read the current page again before continuing.",
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("refuses a child launch callback when the conversation cannot run", () => {
    const props = { ...defaults(), canRun: false };
    render(<WorkspacePanels {...props} />, { wrapper });
    // The real child disables its action; the parent must also reject the callback.
    const start = vi.mocked(BrowserPanel).mock.lastCall![0].onStart!;

    act(() => start("computer"));

    expect(props.onSend).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(useBrowserPanelStore.getState().surface).toBeNull();
  });

  it("opens the browser destination form without sending when a child supplies no URL", () => {
    const props = defaults();
    render(<WorkspacePanels {...props} />, { wrapper });
    const start = vi.mocked(BrowserPanel).mock.lastCall![0].onStart!;

    act(() => start("browser"));

    expect(screen.getByRole("textbox", { name: "Website address" })).toHaveValue("");
    expect(props.onSend).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it.each([
    [
      { teamRoom: true, agentId: null, canRun: false },
      /Mention the agent you want in the room composer/,
    ],
    [{ hostedCapabilities: null }, /configuration is not available/],
    [{ hostedCapabilities: [] }, /not configured for hosted computer/],
    [{ agentId: null }, /Select an agent/],
    [{ busy: true }, /current turn/],
    [{ connected: false }, /Reconnect/],
    [{ agentUsesLocalTools: true }, /tools on your own computer/],
  ] as const)("keeps the opener useful while start is unavailable: %j", async (changes, reason) => {
    const props = { ...defaults(), ...changes };
    render(<WorkspacePanels {...props} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
    expect(screen.getByRole("status")).toHaveTextContent(reason);
    expect(screen.getByRole("button", { name: "Ask agent to start computer" })).toBeDisabled();
    fireEvent.submit(
      screen.getByRole("button", { name: "Ask agent to start computer" }).closest("form")!,
    );
    expect(props.onSend).not.toHaveBeenCalled();
  });

  it.each([
    { readOnly: true },
    { canRun: false },
    { loading: true },
    { teamRoom: true, readOnly: true, agentId: null, canRun: false },
  ])("does not offer a start action without permission or loaded access: %j", async (change) => {
    render(<WorkspacePanels {...defaults()} {...change} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
    expect(screen.getByRole("status")).toHaveTextContent(/cannot start a session/);
    expect(screen.queryByRole("button", { name: "Ask agent to start computer" })).toBeNull();
  });

  it.each(["browser", "computer", "folder", "coding", "skills"] as const)(
    "refuses effective local %s context without changing it",
    async (kind) => {
      const state = useWorkOnStore.getState();
      if (kind === "browser") saveChatControlPreferences({ browser: true });
      else if (kind === "computer") state.setComputer("conversation", true);
      else if (kind === "folder")
        state.set("conversation", { folder: "C:/owned", mode: "read_only" }, false);
      else if (kind === "coding") state.setCoding("conversation", "claude_code");
      else state.setSkills("conversation", ["claude"]);
      const before = JSON.stringify(useWorkOnStore.getState());
      const props = defaults();
      render(<WorkspacePanels {...props} />, { wrapper });
      await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
      expect(screen.getByRole("status")).toHaveTextContent(/tools on your own computer/);
      expect(screen.getByRole("button", { name: "Ask agent to start computer" })).toBeDisabled();
      expect(JSON.stringify(useWorkOnStore.getState())).toBe(before);
      expect(props.onSend).not.toHaveBeenCalled();
    },
  );

  it("keeps computer selected when browser activity arrives, shows its real last view, and stays closed afterwards", async () => {
    const props = defaults();
    const page = view("page", {
      navigable: true,
      title: "Example Domain",
      url: "https://example.com",
    });
    const desktop = view("desktop", {
      title: "Example Domain",
      url: "https://example.com",
      outcome: "done",
    });
    const sources = new Map([["desktop", "computer" as const]]);
    const test = render(<WorkspacePanels {...props} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
    test.rerender(<WorkspacePanels {...props} browses={[page]} />);
    expect(screen.getByRole("heading", { name: "Computer" })).toBeVisible();
    expect(live.calls).toEqual([]);
    test.rerender(<WorkspacePanels {...props} browses={[page, desktop]} surfaces={sources} />);
    expect(screen.getByRole("heading", { name: "Computer" })).toBeVisible();
    expect(screen.getByText("Last view")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Example Domain" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Browser options" })).toBeNull();
    expect(live.calls.at(-1)).toEqual(["actual-run", "desktop", true]);
    await userEvent.click(screen.getByRole("button", { name: "Ask agent to start computer" }));
    expect(props.onSend).toHaveBeenCalledOnce();
    fireEvent.keyDown(window, { key: "Escape" });
    test.rerender(
      <WorkspacePanels
        {...props}
        browses={[page, view("new", { navigable: true, runId: "another-run" })]}
      />,
    );
    expect(useBrowserPanelStore.getState().surface).toBeNull();
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("keeps real room browser and computer views available without offering personal starts", async () => {
    const props = { ...defaults(), teamRoom: true, agentId: null, canRun: false };
    const page = view("page", { navigable: true, title: "Example Domain", outcome: "done" });
    const desktop = view("desktop", { outcome: "done" });
    render(
      <WorkspacePanels
        {...props}
        browses={[page, desktop]}
        surfaces={new Map([["desktop", "computer"]])}
      />,
      { wrapper },
    );
    await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
    expect(live.calls.at(-1)).toEqual(["actual-run", "page", true]);
    expect(screen.queryByRole("button", { name: "Ask agent to open browser" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
    expect(live.calls.at(-1)).toEqual(["actual-run", "desktop", true]);
    expect(screen.getByText("Last view")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Ask agent to start computer" })).toBeNull();
    expect(props.onSend).not.toHaveBeenCalled();
  });

  it("uses the existing Files listing in a closable narrow-screen drawer, never provisioning a workspace", async () => {
    const props = defaults();
    render(<WorkspacePanels {...props} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: /Show the files/ }));
    const drawer = screen.getByRole("complementary", { name: "Files" });
    expect(drawer).toHaveClass("fixed");
    expect(drawer.className).toContain("@min-[900px]/browser-layout:relative");
    expect(apiClient.post).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("complementary")).toBeNull());
    expect(props.onSend).not.toHaveBeenCalled();
  });
});

describe("workspace selection ownership", () => {
  it("follows the newly requested desktop after starting from an explicitly selected historical view", async () => {
    const props = defaults();
    const old = view("historical", { outcome: "done" });
    const sources = new Map([
      ["historical", "computer" as const],
      ["fresh", "computer" as const],
    ]);
    useBrowserPanelStore.getState().open("historical", "computer");
    const test = render(<WorkspacePanels {...props} browses={[old]} surfaces={sources} />, {
      wrapper,
    });
    expect(live.calls.at(-1)?.[1]).toBe("historical");
    await userEvent.click(screen.getByRole("button", { name: "Ask agent to start computer" }));
    expect(props.onSend).toHaveBeenCalledOnce();
    expect(useBrowserPanelStore.getState()).toMatchObject({
      surface: "computer",
      openCallId: null,
    });
    test.rerender(
      <WorkspacePanels
        {...props}
        browses={[old, view("fresh", { runId: "new-run" })]}
        surfaces={sources}
      />,
    );
    expect(live.calls.at(-1)).toEqual(["new-run", "fresh", true]);
  });

  it("rechecks saved local defaults while an idle pane remains open", async () => {
    const props = defaults();
    render(<WorkspacePanels {...props} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
    expect(screen.getByRole("button", { name: "Ask agent to start computer" })).toBeEnabled();
    act(() => saveChatControlPreferences({ browser: true }));
    expect(screen.getByRole("button", { name: "Ask agent to start computer" })).toBeDisabled();
    act(() => saveChatControlPreferences({ browser: false }));
    expect(screen.getByRole("button", { name: "Ask agent to start computer" })).toBeEnabled();
    expect(props.onSend).not.toHaveBeenCalled();
  });
  it.each(["agent", "conversation", "organization", "account"])(
    "closes the old selection on %s switch",
    async (kind) => {
      const props = defaults();
      const test = render(<WorkspacePanels {...props} />, { wrapper });
      await userEvent.click(screen.getByRole("button", { name: "Open Browser" }));
      if (kind === "agent") test.rerender(<WorkspacePanels {...props} agentId="other-agent" />);
      else if (kind === "conversation")
        test.rerender(<WorkspacePanels {...props} conversationId="other-conversation" />);
      else if (kind === "organization")
        act(() => useOrgStore.setState({ activeOrgId: "other-org" }));
      else act(() => useAuthStore.setState({ user: { id: "other-user" } as never }));
      expect(useBrowserPanelStore.getState().surface).toBeNull();
    },
  );
  it("clears an unavailable settings selection on mount and when opened later", () => {
    const props = { ...defaults(), agentId: null };
    useBrowserPanelStore.getState().openSurface("settings");
    render(<WorkspacePanels {...props} />, { wrapper });
    expect(useBrowserPanelStore.getState().surface).toBeNull();
    expect(screen.queryByRole("button", { name: "Open agent settings" })).toBeNull();
    act(() => useBrowserPanelStore.getState().openSurface("settings"));
    expect(useBrowserPanelStore.getState().surface).toBeNull();
  });
  it("closes settings when the selected agent disappears", () => {
    const props = defaults();
    const test = render(<WorkspacePanels {...props} />, { wrapper });
    act(() => useBrowserPanelStore.getState().openSurface("settings"));
    expect(useBrowserPanelStore.getState().surface).toBe("settings");
    expect(screen.getByRole("complementary", { name: "Agent settings" })).toHaveAttribute(
      "id",
      screen.getByRole("button", { name: "Open agent settings" }).getAttribute("aria-controls"),
    );
    test.rerender(<WorkspacePanels {...props} agentId={null} />);
    expect(useBrowserPanelStore.getState().surface).toBeNull();
  });
  it("keeps an explicitly opened pane when its first turn gets a conversation ID", async () => {
    const props = { ...defaults(), conversationId: null };
    const test = render(<WorkspacePanels {...props} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
    test.rerender(<WorkspacePanels {...props} conversationId="created" busy />);
    expect(useBrowserPanelStore.getState().surface).toBe("computer");
  });
  it("resets an idle new-chat pane when an existing conversation is opened", async () => {
    const props = { ...defaults(), conversationId: null };
    const test = render(<WorkspacePanels {...props} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: "Open Computer" }));
    test.rerender(<WorkspacePanels {...props} conversationId="existing" loading />);
    expect(useBrowserPanelStore.getState().surface).toBeNull();
  });
  it("keeps concurrent chat scopes independent", async () => {
    const props = defaults();
    render(
      <>
        <section aria-label="First">
          <ChatScope agentId="agent">
            <WorkspacePanels {...props} />
          </ChatScope>
        </section>
        <section aria-label="Second">
          <ChatScope agentId="agent">
            <WorkspacePanels {...props} />
          </ChatScope>
        </section>
      </>,
      { wrapper },
    );
    const first = within(screen.getByRole("region", { name: "First" }));
    const second = within(screen.getByRole("region", { name: "Second" }));
    await userEvent.click(first.getByRole("button", { name: "Open Browser" }));
    await userEvent.click(second.getByRole("button", { name: "Open Computer" }));
    expect(first.getByRole("heading", { name: "Browser" })).toBeVisible();
    expect(second.getByRole("heading", { name: "Computer" })).toBeVisible();
    const firstId = first
      .getByRole("button", { name: "Open Browser" })
      .getAttribute("aria-controls");
    const secondId = second
      .getByRole("button", { name: "Open Computer" })
      .getAttribute("aria-controls");
    expect(first.getByRole("complementary")).toHaveAttribute("id", firstId);
    expect(second.getByRole("complementary")).toHaveAttribute("id", secondId);
    expect(firstId).not.toBe(secondId);
    await userEvent.click(first.getByRole("button", { name: "Open agent settings" }));
    await userEvent.click(second.getByRole("button", { name: "Open agent settings" }));
    const firstSettingsId = first
      .getByRole("button", { name: "Open agent settings" })
      .getAttribute("aria-controls");
    const secondSettingsId = second
      .getByRole("button", { name: "Open agent settings" })
      .getAttribute("aria-controls");
    expect(first.getByRole("complementary", { name: "Agent settings" })).toHaveAttribute(
      "id",
      firstSettingsId,
    );
    expect(second.getByRole("complementary", { name: "Agent settings" })).toHaveAttribute(
      "id",
      secondSettingsId,
    );
    expect(firstSettingsId).not.toBe(secondSettingsId);
    expect(useBrowserPanelStore.getState().surface).toBeNull();
  });
});
