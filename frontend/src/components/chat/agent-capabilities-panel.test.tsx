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
  versionError: null as Error | null,
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
    error: env.versionError,
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

const GMAIL: McpConnectionRecord = {
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
};

const open = () => userEvent.click(screen.getByRole("button", { name: "What can this agent do" }));

function phone(matches: boolean) {
  vi.mocked(window.matchMedia).mockImplementation(
    (query: string) =>
      ({
        matches,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }) as unknown as MediaQueryList,
  );
}

describe("AgentCapabilitiesPanel", () => {
  beforeEach(() => {
    phone(false);
    env.agent = { ...AGENT };
    env.catalog = [entry({ id: "knowledge" })];
    env.catalogLoading = false;
    env.guides = { knowledge: KNOWLEDGE_GUIDE };
    env.bindings = [];
    env.versionLoading = false;
    env.versionError = null;
    env.connections = [];
    env.connectionsLoading = false;
    env.servers = [];
    env.serversLoading = false;
  });

  it("is a collapsed control that mounts none of the content", () => {
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);

    const control = screen.getByRole("button", { name: "What can this agent do" });
    expect(control).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Knowledge")).toBeNull();
    expect(screen.queryByRole("button", { name: "Find the refund policy" })).toBeNull();
  });

  it("opens what the agent can do, in plain words, with something to try", async () => {
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);
    await open();

    expect(screen.getByRole("button", { name: "What can this agent do" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("Knowledge")).toBeInTheDocument();
    expect(screen.getByText(/Answers from your documents\./)).toBeInTheDocument();
  });

  it("sends an example, closes, and returns focus to the control", async () => {
    const onPick = vi.fn();
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={onPick} />);
    await open();

    await userEvent.click(screen.getByRole("button", { name: "Find the refund policy" }));

    expect(onPick).toHaveBeenCalledWith("Find the refund policy");
    expect(screen.queryByText("Knowledge")).toBeNull();
    expect(screen.getByRole("button", { name: "What can this agent do" })).toHaveFocus();
  });

  it("returns focus to the control when closed with Escape", async () => {
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);
    await open();
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByText("Knowledge")).toBeNull();
    expect(screen.getByRole("button", { name: "What can this agent do" })).toHaveFocus();
  });

  it("opens in a sheet on a phone", async () => {
    phone(true);
    const onPick = vi.fn();
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={onPick} />);
    await open();

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What can this agent do" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Find the refund policy" }));
    expect(onPick).toHaveBeenCalledWith("Find the refund policy");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "What can this agent do" })).toHaveFocus();
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
    return open().then(() => {
      expect(screen.getByText("Apps set up for this agent: Gmail · Notion")).toBeInTheDocument();
    });
  });

  it("says plainly when the agent has no bindings at all", async () => {
    env.agent = { ...AGENT, published_capabilities: [] };
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);
    await open();

    expect(screen.getByText(/This agent has no tools or apps yet\./)).toBeInTheDocument();
  });

  it("shows no control while any list it reads from is still loading", () => {
    env.catalogLoading = true;
    const { rerender } = render(
      <AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "What can this agent do" })).toBeNull();

    env.catalogLoading = false;
    env.versionLoading = true;
    rerender(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "What can this agent do" })).toBeNull();
  });

  it("shows no control when the agent is bound to something the catalog cannot name", () => {
    // A failed catalog lookup leaves no rows for a capable agent: that is a
    // lookup failure, not an agent with nothing to do, so no plain "no tools"
    // line is drawn.
    env.catalog = [];
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "What can this agent do" })).toBeNull();
  });

  it("shows no control when the version lookup failed for an app-only agent", () => {
    // An agent bound only to apps has no published capabilities, so a failed
    // version lookup leaves it looking empty: a lookup failure, not "no tools".
    env.agent = { ...AGENT, published_capabilities: [] };
    env.versionError = new Error("502");
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "What can this agent do" })).toBeNull();
  });

  it("makes no connection claim about a disabled org app or a personal app", async () => {
    env.bindings = [
      { account: "organization", connection_id: "gmail", allowed_tools: null, approval: "writes" },
      { account: "personal", catalog_key: "notion", allowed_tools: null, approval: "writes" },
    ];
    env.connections = [{ ...GMAIL, is_enabled: false }];
    render(<AgentCapabilitiesPanel agent={env.agent as Agent} onPick={vi.fn()} />);
    await open();

    expect(screen.getByText("Apps set up for this agent: Gmail · notion")).toBeInTheDocument();
    expect(screen.queryByText(/connected/i)).toBeNull();
  });

  it("renders nothing before the agent resolves", () => {
    render(<AgentCapabilitiesPanel agent={undefined} onPick={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "What can this agent do" })).toBeNull();
  });
});
