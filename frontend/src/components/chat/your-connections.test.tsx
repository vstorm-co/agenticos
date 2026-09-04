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
vi.mock("@/components/agents/connect-server-dialog", () => ({
  ConnectOwnServerDialog: ({ entry }: { entry: McpCatalogEntry | null }) =>
    entry ? <div role="dialog">connecting {entry.name}</div> : null,
}));

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
    auth_type: "oauth",
    oauth_authorized: true,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
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
    state.bindings = [{ account: "personal", catalog_key: "notion", allowed_tools: null }];
    state.connections = [];
  });

  it("renders nothing for an agent whose bindings are all the organization's", () => {
    state.bindings = [{ account: "organization", connection_id: "c1", allowed_tools: null }];
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

  it("sends a person with several accounts and no default to the servers page", () => {
    state.connections = [own(), own({ id: "m2", name: "notion-2" })];
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    render(<YourConnections />);

    expect(screen.getByText("Several accounts, none marked default")).toBeInTheDocument();
    screen.getByRole("button", { name: "Open MCP servers" }).click();

    expect(opened).toHaveBeenCalledWith("/mcp-servers", "_blank", "noopener");
  });

  it("says when the chosen account no longer authorizes", () => {
    state.connections = [own({ oauth_authorized: false })];
    render(<YourConnections />);

    expect(screen.getByText("Needs authorizing again")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open MCP servers" })).toBeInTheDocument();
  });
});
