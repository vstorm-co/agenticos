import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentCapabilitiesPanel } from "./agent-capabilities-panel";
import type { CapabilityGuide } from "@/hooks/use-capability-guide";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { Agent, CapabilityCatalogEntry, McpServerRef } from "@/types/agents";
import type { McpCatalogEntry } from "@/types/mcp";

const env = vi.hoisted(() => ({
  agent: null as Partial<Agent> | null,
  catalog: [] as CapabilityCatalogEntry[],
  catalogLoading: false,
  guides: {} as Record<string, CapabilityGuide>,
  bindings: [] as McpServerRef[],
  versionLoading: false,
  connections: [] as McpConnectionRecord[],
  connectionsLoading: false,
  servers: [] as McpCatalogEntry[],
  serversLoading: false,
}));

vi.mock("@/hooks", () => ({
  useCapabilityCatalog: () => ({ capabilities: env.catalog, isLoading: env.catalogLoading }),
  useAgentVersion: () => ({
    version:
      env.agent?.current_version_id === undefined
        ? undefined
        : { spec: { mcp_servers: env.bindings } },
    isLoading: env.versionLoading,
    error: null,
  }),
  useMcpConnections: () => ({ connections: env.connections, isLoading: env.connectionsLoading }),
  useMcpCatalog: () => ({ servers: env.servers, isLoading: env.serversLoading }),
}));
vi.mock("@/hooks/use-capability-guide", () => ({
  useCapabilityGuide: () => (id: string) => env.guides[id],
}));

function entry(
  overrides: Partial<CapabilityCatalogEntry> & { id: string },
): CapabilityCatalogEntry {
  return {
    name: overrides.id,
    category: "general",
    description: `${overrides.id} description`,
    side_effecting: false,
    scopes: [],
    tools: [{ id: `${overrides.id}-tool`, name: overrides.id, description: "Does it." }],
    contracts: [],
    config_schema: null,
    requires_secret: null,
    voice: "never",
    recommended: null,
    ...overrides,
  };
}

const KNOWLEDGE_GUIDE: CapabilityGuide = {
  name: "Knowledge",
  does: "Answers from your documents.",
  examples: ["Find the refund policy"],
  needs: "A collection.",
  never: "Never invents a source.",
};

const AGENT: Partial<Agent> = {
  id: "a1",
  slug: "amigo",
  name: "Amigo",
  current_version_id: "v1",
  published_capabilities: ["knowledge"],
};

describe("AgentCapabilitiesPanel", () => {
  beforeEach(() => {
    env.agent = { ...AGENT };
    env.catalog = [entry({ id: "knowledge" })];
    env.catalogLoading = false;
    env.guides = { knowledge: KNOWLEDGE_GUIDE };
    env.bindings = [];
    env.versionLoading = false;
    env.connections = [];
    env.connectionsLoading = false;
    env.servers = [];
    env.serversLoading = false;
  });

  it("lists what the agent can do, in plain words, with something to try", async () => {
    const onPick = vi.fn();
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={onPick} />);

    expect(screen.getByRole("heading", { name: "What can this agent do" })).toBeInTheDocument();
    expect(screen.getByText("Knowledge")).toBeInTheDocument();
    expect(screen.getByText(/Answers from your documents\./)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Find the refund policy" }));
    expect(onPick).toHaveBeenCalledWith("Find the refund policy");
  });

  it("names the connected apps the agent is bound to", () => {
    env.bindings = [
      { account: "organization", connection_id: "gmail", allowed_tools: null, approval: "writes" },
      { account: "personal", catalog_key: "notion", allowed_tools: null, approval: "writes" },
    ];
    env.connections = [
      {
        id: "gmail",
        name: "Gmail",
        url: "https://example.com/mcp",
        has_auth_token: false,
        allowed_tools: null,
        is_enabled: true,
        include_instructions: false,
        auth_type: "oauth",
        oauth_authorized: true,
        authorized: true,
        last_status: null,
        last_error: null,
        last_checked_at: null,
        visibility: "org",
        catalog_key: "gmail",
        label: null,
        is_default: false,
        trust_read_only_hints: false,
        last_tools: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: null,
      },
    ];
    env.servers = [
      {
        key: "notion",
        name: "Notion",
        description: "Pages and databases.",
        category: "productivity",
        auth: "oauth",
        url: null,
        docs_url: null,
        token_hint: null,
        icon: null,
        reviewed: true,
        verified: false,
        check: null,
        custom: false,
        connection_ids: null,
      },
    ];
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);

    expect(screen.getByText("Connected apps: Gmail · Notion")).toBeInTheDocument();
  });

  it("says plainly when the agent has no bindings at all", () => {
    env.agent = { ...AGENT, published_capabilities: [] };
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "What can this agent do" })).toBeInTheDocument();
    expect(screen.getByText(/This agent has no tools or connected apps yet\./)).toBeInTheDocument();
  });

  it("says nothing while any list it reads from is still loading", () => {
    env.catalogLoading = true;
    const { rerender } = render(
      <AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />,
    );
    expect(screen.queryByRole("heading", { name: "What can this agent do" })).toBeNull();

    env.catalogLoading = false;
    env.versionLoading = true;
    rerender(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);
    expect(screen.queryByRole("heading", { name: "What can this agent do" })).toBeNull();
  });

  it("says nothing when the agent is bound to something the catalog cannot name", () => {
    // A failed catalog lookup leaves no rows for a capable agent: that is a
    // lookup failure, not an agent with nothing to do, so no plain "no tools"
    // line is drawn.
    env.catalog = [];
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);

    expect(screen.queryByRole("heading", { name: "What can this agent do" })).toBeNull();
  });

  it("renders nothing before the agent resolves", () => {
    render(<AgentCapabilitiesPanel agent={undefined} onPick={vi.fn()} />);

    expect(screen.queryByRole("heading", { name: "What can this agent do" })).toBeNull();
  });
});
