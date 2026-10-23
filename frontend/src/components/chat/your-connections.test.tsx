import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { YourConnections } from "./your-connections";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { McpServerRef } from "@/types/agents";
import type { McpCatalogEntry } from "@/types/mcp";

const state = vi.hoisted(() => ({
  selectedAgentId: "a1" as string | null,
  bindings: [] as McpServerRef[],
  connections: [] as McpConnectionRecord[],
}));

vi.mock("@/stores", () => ({
  useAgentSelectionStore: (pick: (s: { selectedAgentId: string | null }) => unknown) =>
    pick({ selectedAgentId: state.selectedAgentId }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({ agents: [{ id: "a1", current_version_id: "v1" }] }),
  useAgentVersion: (agentId: string | null, versionId: string | null) => ({
    version: agentId && versionId ? { spec: { mcp_servers: state.bindings } } : undefined,
    isLoading: false,
    error: null,
  }),
}));
vi.mock("@/hooks/use-mcp-connections", () => ({
  useMcpConnections: () => ({ connections: state.connections }),
}));
vi.mock("@/hooks/use-mcp-servers", () => ({
  useMcpCatalog: () => ({ servers: [NOTION], isLoading: false }),
}));
// The button and its dialog are tested on their own; here it only has to be
// offered for the right entry, so clicking it renders a marker naming that one.
vi.mock("@/components/agents/connect-server-dialog", async () => {
  const { useState } = await import("react");
  return {
    ConnectOwnButton: ({ entry, label }: { entry: McpCatalogEntry; label: string }) => {
      const [open, setOpen] = useState(false);
      return open ? (
        <div role="dialog">
          connecting {entry.name}
          <button type="button" onClick={() => setOpen(false)}>
            close
          </button>
        </div>
      ) : (
        <button type="button" onClick={() => setOpen(true)}>
          {label}
        </button>
      );
    },
  };
});

const NOTION: McpCatalogEntry = {
  key: "notion",
  name: "Notion",
  description: "Pages and databases.",
  category: "productivity",
  auth: "oauth",
  url: "https://mcp.notion.com/mcp",
  docs_url: null,
  token_hint: null,
  icon: "notion",
};

function own(overrides: Partial<McpConnectionRecord> = {}): McpConnectionRecord {
  return {
    id: "m1",
    name: "notion",
    url: "https://mcp.notion.com/mcp",
    has_auth_token: true,
    allowed_tools: null,
    is_enabled: true,
    include_instructions: false,
    auth_type: "oauth",
    oauth_authorized: true,
    authorized: true,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    visibility: "org",
    catalog_key: "notion",
    is_default: false,
    label: null,
    last_tools: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

describe("YourConnections", () => {
  beforeEach(() => {
    state.selectedAgentId = "a1";
    state.bindings = [
      { account: "personal", catalog_key: "notion", allowed_tools: null, approval: "none" },
    ];
    state.connections = [];
  });

  it("renders nothing for an agent whose bindings are all the organization's", () => {
    state.bindings = [
      { account: "organization", connection_id: "c1", allowed_tools: null, approval: "none" },
    ];
    const { container } = render(<YourConnections />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while no agent is selected", () => {
    state.selectedAgentId = null;
    const { container } = render(<YourConnections />);

    expect(container).toBeEmptyDOMElement();
  });

  it("lists a personal service the person has not connected, with a way to", async () => {
    render(<YourConnections />);

    expect(screen.getByText("Notion")).toBeInTheDocument();
    expect(screen.getByText("Not connected")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(screen.getByRole("dialog")).toHaveTextContent("connecting Notion");
  });

  it("says connected when one account of theirs answers", () => {
    state.connections = [own()];
    render(<YourConnections />);

    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says connected with several accounts and none marked main - every one answers", () => {
    state.connections = [own(), own({ id: "m2", name: "notion-2" })];
    render(<YourConnections />);

    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("says when the chosen account no longer authorizes", async () => {
    // The server decides usability now; the client reads `authorized` rather than
    // re-deriving it from OAuth consent alone (#1443).
    state.connections = [own({ oauth_authorized: false, authorized: false })];
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<YourConnections />);

    expect(screen.getByText("Needs authorizing again")).toBeInTheDocument();
    // In a new tab: the conversation, and the question in it, stay where they are.
    await userEvent.click(screen.getByRole("button", { name: "Open MCP servers" }));
    expect(open).toHaveBeenCalledWith("/mcp-servers", "_blank", "noopener");
    open.mockRestore();
  });
});

describe("YourConnections' dialog", () => {
  it("closes when the person backs out of connecting", async () => {
    state.selectedAgentId = "a1";
    state.bindings = [
      { account: "personal", catalog_key: "notion", allowed_tools: null, approval: "none" },
    ];
    state.connections = [];
    render(<YourConnections />);
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    await userEvent.click(screen.getByRole("button", { name: "close" }));

    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("YourConnections and a key the catalog no longer holds", () => {
  it("names the service by its key and sends the person to the servers page", () => {
    state.selectedAgentId = "a1";
    state.bindings = [
      { account: "personal", catalog_key: "gone", allowed_tools: null, approval: "none" },
    ];
    state.connections = [];
    render(<YourConnections />);

    expect(screen.getByText("gone")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open MCP servers" })).toBeInTheDocument();
  });
});
