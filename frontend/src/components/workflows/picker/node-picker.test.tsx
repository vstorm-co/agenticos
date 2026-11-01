import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NODE_DRAG_MIME } from "@/components/workflows/palette";
import { makeDefinition } from "@/components/workflows/validation/fixtures";
import { useWorkflowNodeStyleStore } from "@/stores/workflow-node-style-store";

import type { UsableMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

import type { McpCatalogEntry } from "@/types/mcp";
import { NodePicker } from "./node-picker";

const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/components/workflows/pickers/workflow-connections-dialog", () => ({
  WorkflowConnectionsDialog: ({
    catalogKey,
    onOpenChange,
  }: {
    catalogKey?: string;
    onOpenChange: (open: boolean) => void;
  }) => <button onClick={() => onOpenChange(false)}>Connect {catalogKey}</button>,
}));

const refreshTools = vi.hoisted(() => vi.fn());
const apps = vi.hoisted(() => ({
  connections: null as UsableMcpConnectionRecord[] | null,
  canConnect: false,
  unavailable: false,
  servers: [] as McpCatalogEntry[],
}));
vi.mock("@/components/workflows/use-app-connections", () => ({
  useAppConnections: () => apps,
  useRefreshWorkflowMcpTools: () => ({ mutate: refreshTools, isPending: false, isError: false }),
}));

const SEND = makeDefinition({
  id: "slack.message.send",
  category: "slack",
  name: "Send a message",
  description: "Post to Slack",
});
const READ = makeDefinition({
  id: "slack.messages.read",
  category: "slack",
  name: "Read messages",
  description: "Read Slack",
});
const AGENT = makeDefinition({
  id: "agent.run",
  category: "agent",
  name: "Run an agent",
  description: "Ask an agent",
});
const OFFERED = [READ, SEND, AGENT];

function mount(draggable = false) {
  const onPick = vi.fn();
  render(<NodePicker offered={OFFERED} onPick={onPick} draggable={draggable} />);
  return onPick;
}

beforeEach(() => {
  useWorkflowNodeStyleStore.setState({ style: "colour" });
  apps.connections = null;
  apps.canConnect = false;
  apps.unavailable = false;
  apps.servers = [];
  router.push.mockReset();
});

describe("NodePicker", () => {
  it("draws each tile in its family, and a swatch beside a section's heading", async () => {
    mount();
    const row = (name: RegExp) => screen.getByRole("option", { name });
    expect(row(/Run an agent/).querySelector("[data-node-family]")).toHaveClass("node-tile-ai");
    expect(row(/^Slack/).querySelector("[data-node-family]")).toHaveClass("node-tile-apps");
    expect(screen.getByText("AI").querySelector("span[aria-hidden]")).not.toBeNull();

    await userEvent.click(row(/^Slack/));
    expect(row(/Send a message/).querySelector("[data-node-family]")).toHaveClass("node-tile-apps");
  });

  it("draws neutral tiles and no swatch in Simple", () => {
    useWorkflowNodeStyleStore.setState({ style: "simple" });
    mount();
    expect(screen.getByRole("option", { name: /Run an agent/ }).querySelector("span")).toHaveClass(
      "bg-muted",
    );
    expect(screen.getByText("AI").querySelector("span[aria-hidden]")).toBeNull();
  });

  it("lists sections of groups, a lone step at once, and a group's steps one level down", async () => {
    const onPick = mount();
    expect(screen.getByText("AI")).toBeTruthy();
    expect(screen.getByText("Apps and the web")).toBeTruthy();
    // A group of one step is that step.
    await userEvent.click(screen.getByRole("option", { name: /Run an agent/ }));
    expect(onPick).toHaveBeenCalledWith(AGENT);

    await userEvent.click(screen.getByRole("option", { name: /^Slack/ }));
    const rows = screen.getAllByRole("option").map((row) => row.textContent ?? "");
    // Acting first: send before read, whatever order the catalog had.
    expect(rows.findIndex((row) => row.includes("Send a message"))).toBeLessThan(
      rows.findIndex((row) => row.includes("Read messages")),
    );
    expect(screen.getByText("Post, read and look up in Slack")).toBeTruthy();
    // The group's name heads its steps; it is not a row that looks like one.
    expect(screen.queryByRole("option", { name: /^Slack/ })).toBeNull();
    const group = screen.getByRole("group", { name: /^Slack/ });
    expect(group.textContent).toContain("Send a message");
    expect(group.textContent).toContain("Read messages");
    await userEvent.click(screen.getByRole("option", { name: /Send a message/ }));
    expect(onPick).toHaveBeenLastCalledWith(SEND);

    await userEvent.click(screen.getByRole("option", { name: "All steps" }));
    expect(screen.getByText("AI")).toBeTruthy();
  });

  it("leaves a group on Backspace in an empty search, and searches every step at once", async () => {
    const onPick = mount();
    await userEvent.click(screen.getByRole("option", { name: /^Slack/ }));
    const search = screen.getByPlaceholderText("Search steps");
    fireEvent.keyDown(search, { key: "Backspace" });
    expect(screen.getByText("AI")).toBeTruthy();

    await userEvent.type(search, "read");
    expect(screen.queryByText("AI")).toBeNull();
    expect(screen.getByText("Read messages")).toBeTruthy();
    expect(screen.getByText("Slack")).toBeTruthy();
    await userEvent.click(screen.getByRole("option", { name: /Read messages/ }));
    expect(onPick).toHaveBeenCalledWith(READ);

    await userEvent.clear(search);
    await userEvent.type(search, "zzz");
    expect(screen.getByText("No nodes match your search.")).toBeTruthy();
    // Backspace with text in the box edits the text, and stays in the results.
    fireEvent.keyDown(search, { key: "Backspace" });
    expect(screen.queryByText("AI")).toBeNull();
  });

  it("puts a step whose name matches before one whose description does", async () => {
    mount();
    // "Read Slack" mentions it; only "Send a message" is named for it.
    await userEvent.type(screen.getByPlaceholderText("Search steps"), "message");
    const rows = screen.getAllByRole("option").map((row) => row.textContent);
    expect(rows[0]).toMatch(/^Send a message/);
    expect(rows[1]).toMatch(/^Read messages/);
  });

  it("lets a row be dragged onto the canvas when the picker allows it", () => {
    mount(true);
    const row = screen.getByRole("option", { name: /Run an agent/ });
    const setData = vi.fn();
    fireEvent.dragStart(row, { dataTransfer: { setData, effectAllowed: "" } });
    expect(setData).toHaveBeenCalledWith(NODE_DRAG_MIME, expect.stringContaining("agent.run"));
  });
});

describe("NodePicker app groups", () => {
  const GMAIL = makeDefinition({
    id: "trigger.gmail",
    category: "triggers",
    name: "Gmail",
    description: "A new message",
  });
  const MANUAL = makeDefinition({
    id: "trigger.manual",
    category: "triggers",
    name: "Manual",
    description: "Run by hand",
  });
  const MCP_CALL = makeDefinition({
    id: "mcp.call",
    category: "mcp",
    name: "Call an MCP tool",
    description: "Call a tool on a server",
  });
  const connection = (overrides: Partial<UsableMcpConnectionRecord> = {}) =>
    ({
      id: "c1",
      name: "gmail-dev",
      label: null,
      catalog_key: "google-workspace",
      is_enabled: true,
      allowed_tools: null,
      last_tools: [
        { name: "draft_gmail_message", description: "Draft a message" },
        { name: "list_gmail_drafts", description: "List drafts" },
      ],
      ...overrides,
    }) as UsableMcpConnectionRecord;

  function mountApps(offered = [GMAIL, MANUAL, MCP_CALL, AGENT]) {
    const onPick = vi.fn();
    render(<NodePicker offered={offered} onPick={onPick} />);
    return onPick;
  }
  const openGmail = async () =>
    userEvent.click(screen.getByRole("option", { name: /Mail trigger and Gmail actions/ }));

  const openServerGroup = async () =>
    userEvent.click(screen.getByRole("option", { name: /^Google Workspace/ }));

  it("groups the trigger and each tool of the organization's connection, MCP badge and all", async () => {
    apps.connections = [connection()];
    const onPick = mountApps();
    // App tools replace the generic MCP call in the picker.
    expect(screen.queryByRole("option", { name: /Call an MCP tool/ })).toBeNull();
    expect(screen.getByRole("option", { name: /^Gmail/ })).toBeTruthy();

    await openGmail();
    const group = screen.getByRole("group", { name: /^Gmail/ });
    const trigger = within(group).getByRole("option", { name: /^Gmail/ });
    // The native trigger is not an MCP call, so it carries no badge.
    expect(trigger.textContent).not.toContain("MCP");

    const draft = within(group).getByRole("option", { name: /Create draft/ });
    expect(draft.textContent).toContain("MCP");
    expect(draft.textContent).toContain("gmail-dev");
    // The server is said once, in the group's heading, not in every row.
    expect(draft.textContent).not.toContain("Google Workspace");
    expect(document.body.textContent?.match(/Google Workspace \(self-hosted\)/g)).toHaveLength(1);
    expect(draft.textContent).toContain("draft_gmail_message");
    // A tool nobody named is called by its own name, humanized.
    expect(within(group).getByRole("option", { name: /List gmail drafts/ })).toBeTruthy();

    await userEvent.click(draft);
    expect(onPick).toHaveBeenCalledWith(MCP_CALL, {
      connection_id: "c1",
      tool: "draft_gmail_message",
    });
  });

  it("shows an editor who cannot manage servers the actions, and no way to connect when there are none", async () => {
    apps.connections = [connection()];
    apps.canConnect = false;
    const { unmount } = render(<NodePicker offered={[GMAIL, MANUAL, MCP_CALL]} onPick={vi.fn()} />);
    await openGmail();
    expect(screen.getByRole("option", { name: /Create draft/ })).toBeTruthy();
    unmount();

    apps.connections = [];
    render(<NodePicker offered={[GMAIL, MANUAL, MCP_CALL]} onPick={vi.fn()} />);
    await openGmail();
    expect(screen.queryByText(/Connect Google Workspace/)).toBeNull();
    expect(screen.queryByText(/can't edit this workflow/)).toBeNull();
  });

  it("never cuts an action's name, tool or connection, and says the server once in the heading", async () => {
    const tool = "get_gmail_attachment_content_with_a_very_long_name_that_would_not_fit";
    apps.connections = [
      connection({
        name: "a-connection-with-a-long-name",
        last_tools: [{ name: tool, description: "" }],
      }),
    ];
    mountApps();
    await openGmail();

    const row = screen.getByRole("option", { name: /Get gmail attachment content with/ });
    expect(row.querySelector(".truncate, [class*='line-clamp']")).toBeNull();
    expect(within(row).getByText(tool)).toBeTruthy();
    expect(within(row).getByText("a-connection-with-a-long-name")).toBeTruthy();
  });

  it("draws an unconnected catalog service's logo on its picker row", async () => {
    apps.connections = [];
    apps.canConnect = true;
    apps.servers = [
      {
        key: "airtable",
        name: "Airtable",
        description: "",
        category: "productivity",
        auth: "oauth",
        url: "https://mcp.airtable.com/mcp",
        icon: null,
        docs_url: null,
        token_hint: null,
      },
    ];
    mountApps();
    const row = screen.getByRole("option", { name: /^Airtable/ });
    expect(row.querySelector("img")?.getAttribute("src")).toMatch(/^data:image\//);
    expect(row.querySelector("svg.lucide-zap")).toBeNull();
  });

  it("finds an unconnected catalog service by search and opens it with the search cleared", async () => {
    apps.connections = [];
    apps.canConnect = true;
    apps.servers = [
      {
        key: "airtable",
        name: "Airtable",
        description: "",
        category: "productivity",
        auth: "oauth",
        url: "https://mcp.airtable.com/mcp",
        icon: null,
        docs_url: null,
        token_hint: null,
      },
    ];
    mountApps();
    const search = screen.getByPlaceholderText("Search steps");

    await userEvent.type(search, "airt");
    expect(screen.queryByText("No nodes match your search.")).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: /^Airtable/ }));

    expect(search).toHaveValue("");
    expect(screen.getByRole("option", { name: /Connect Airtable/ })).toBeVisible();
  });

  it("refreshes an untested server inline only for connection managers", async () => {
    apps.connections = [connection({ last_tools: null })];
    apps.canConnect = true;
    const mounted = render(<NodePicker offered={[GMAIL, MANUAL, MCP_CALL]} onPick={vi.fn()} />);
    await openServerGroup();
    await userEvent.click(screen.getByRole("option", { name: "Refresh tools" }));
    expect(refreshTools).toHaveBeenCalledWith("c1");
    mounted.unmount();
    apps.canConnect = false;
    mountApps();
    await openServerGroup();
    expect(screen.queryByRole("option", { name: "Refresh tools" })).toBeNull();
  });

  it("offers the trigger and a way to connect when no connection provides the actions", async () => {
    apps.connections = [connection({ catalog_key: "hubspot" })];
    apps.canConnect = true;
    const onPick = mountApps();
    // Connect sits in the server's own group, not in Gmail's.
    await openGmail();
    expect(screen.queryByText(/Connect Google Workspace/)).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: "All steps" }));
    await openServerGroup();
    await userEvent.click(
      screen.getByRole("option", { name: "Connect Google Workspace to add its actions" }),
    );
    expect(router.push).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Connect google-workspace" }));
    await userEvent.click(screen.getByRole("option", { name: "All steps" }));
    await openGmail();
    await userEvent.click(
      within(screen.getByRole("group", { name: /^Gmail/ })).getByRole("option", { name: /^Gmail/ }),
    );
    expect(onPick).toHaveBeenCalledWith(GMAIL);
  });

  it("does not offer to connect to a member who may not, nor before the list is known", async () => {
    apps.connections = [];
    apps.canConnect = false;
    const { unmount } = render(<NodePicker offered={[GMAIL, MANUAL, MCP_CALL]} onPick={vi.fn()} />);
    await openGmail();
    expect(screen.queryByText(/Connect Google Workspace/)).toBeNull();
    unmount();
  });

  it("lists each connection's tools under its own name when there are several", async () => {
    apps.connections = [
      connection(),
      connection({ id: "c2", name: "gmail-ops", label: "Support inbox" }),
    ];
    const onPick = mountApps();
    await openGmail();
    const drafts = screen.getAllByRole("option", { name: /Create draft/ });
    expect(drafts.map((row) => row.textContent)).toEqual([
      expect.stringContaining("gmail-dev"),
      expect.stringContaining("Support inbox"),
    ]);
    await userEvent.click(drafts[1] as HTMLElement);
    expect(onPick).toHaveBeenCalledWith(MCP_CALL, {
      connection_id: "c2",
      tool: "draft_gmail_message",
    });
  });

  it("leaves out a disabled connection and a tool its allow list holds back, and says when none are listed", async () => {
    apps.connections = [
      connection({ allowed_tools: ["list_gmail_drafts"] }),
      connection({ id: "c2", name: "off", is_enabled: false }),
      connection({ id: "c3", name: "fresh", last_tools: null }),
    ];
    mountApps();
    await openGmail();
    expect(screen.queryByRole("option", { name: /Create draft/ })).toBeNull();
    expect(screen.getByRole("option", { name: /List gmail drafts/ })).toBeTruthy();
    expect(screen.queryByText(/fresh has no tools listed yet/)).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: "All steps" }));
    await openServerGroup();
    expect(screen.getByText(/fresh has no tools listed yet/)).toBeTruthy();
    expect(screen.queryByText(/off/)).toBeNull();
  });

  it("says why a member who cannot edit workflows sees no actions", async () => {
    apps.connections = null;
    apps.unavailable = true;
    mountApps();
    await openServerGroup();
    expect(
      screen.getByText(
        /Google Workspace actions are not shown because you can't edit this workflow/,
      ),
    ).toBeTruthy();
  });

  it("adds no actions when the canvas offers no MCP call", async () => {
    apps.connections = [connection()];
    mountApps([GMAIL, MANUAL]);
    await openGmail();
    expect(screen.queryByRole("option", { name: /Create draft/ })).toBeNull();
  });

  it("finds an action by its friendly name, its raw tool name, its app and its connection", async () => {
    apps.connections = [connection()];
    mountApps();
    const search = screen.getByPlaceholderText("Search steps");

    await userEvent.type(search, "draft_gmail");
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option", { name: /Create draft/ }).textContent).toContain(
      "Gmail · gmail-dev",
    );

    await userEvent.clear(search);
    await userEvent.type(search, "create draft");
    expect(screen.getByRole("option", { name: /Create draft/ })).toBeTruthy();

    // The app's name: its trigger once (under Triggers), then both of its actions.
    await userEvent.clear(search);
    await userEvent.type(search, "gmail");
    const rows = screen.getAllByRole("option").map((row) => row.textContent ?? "");
    expect(rows.filter((row) => row.startsWith("Gmail"))).toHaveLength(1);
    expect(rows).toHaveLength(3);

    await userEvent.clear(search);
    await userEvent.type(search, "gmail-dev");
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });
});
