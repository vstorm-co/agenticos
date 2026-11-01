import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { McpCatalogEntry } from "@/types/mcp";
import type { UsableMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import {
  useAppConnections,
  useMcpAppStep,
  useRefreshWorkflowMcpTools,
} from "./use-app-connections";

vi.mock("@/hooks/use-mcp-servers", () => ({
  useMcpCatalog: () => ({ servers: state.curated }),
  useMcpCatalogPage: () => ({ servers: state.registry }),
  useMcpServerEntry: (key: string | null) => ({
    entry: state.entry?.key === key ? state.entry : null,
  }),
}));

const probe = vi.hoisted(() => vi.fn());
vi.mock("@/lib/org-mcp-connections-api", () => ({ testOrgMcpConnection: probe }));

const gmail = { id: "c1", name: "gmail-dev", label: null, catalog_key: "google-workspace" };
const other = { id: "c2", name: "crm", label: null, catalog_key: "hubspot" };

const state = vi.hoisted(() => ({
  entry: null as McpCatalogEntry | null,
  curated: [] as McpCatalogEntry[],
  registry: [] as McpCatalogEntry[],
  canManage: true,
  // `workflow.can_edit`, not a permission: a grant on one workflow is enough.
  canRead: true,
  loaded: true,
  connections: [] as unknown[],
}));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => state.canManage }),
  useUsableMcpConnections: () => ({
    connections: state.canRead && state.loaded ? state.connections : null,
    isLoading: false,
    canRead: state.canRead,
  }),
}));

beforeEach(() => {
  state.entry = null;
  state.curated = [];
  state.registry = [];
  state.canManage = true;
  state.canRead = true;
  state.loaded = true;
  state.connections = [gmail, other] as UsableMcpConnectionRecord[];
});

describe("useAppConnections", () => {
  it("lists the connections for whoever may edit the workflow, and lets a manager add one", () => {
    const { result } = renderHook(() => useAppConnections());
    expect(result.current).toEqual({
      connections: [gmail, other],
      servers: [],
      canConnect: true,
      unavailable: false,
    });
  });

  it("lists them for an editor who may not manage servers, who cannot connect one", () => {
    state.canManage = false;
    const { result } = renderHook(() => useAppConnections());
    expect(result.current.connections).toHaveLength(2);
    expect(result.current.canConnect).toBe(false);
    expect(result.current.unavailable).toBe(false);
  });

  it("reports the list unknown while loading, which is not unavailable", () => {
    state.loaded = false;
    const { result } = renderHook(() => useAppConnections());
    expect(result.current).toEqual({
      connections: null,
      servers: [],
      canConnect: true,
      unavailable: false,
    });
  });

  it("reports it unavailable where the workflow cannot be edited", () => {
    state.canRead = false;
    const { result } = renderHook(() => useAppConnections());
    expect(result.current).toEqual({
      connections: null,
      servers: [],
      canConnect: true,
      unavailable: true,
    });
  });
});

function server(key: string, name: string): McpCatalogEntry {
  return {
    key,
    name,
    description: "",
    category: "productivity",
    auth: "oauth",
    url: `https://${key}.example.com`,
    icon: key,
    docs_url: null,
    token_hint: null,
  };
}

describe("the server list", () => {
  it("adds the registry's matches to the curated list once a search is open, one per key", () => {
    state.curated = [server("hubspot", "CRM"), server("linear", "Linear")];
    state.registry = [server("hubspot", "CRM again"), server("zendesk", "Support")];

    const closed = renderHook(() => useAppConnections());
    const searching = renderHook(() => useAppConnections("sup"));

    expect(closed.result.current.servers.map((entry) => entry.key)).toEqual(["hubspot", "linear"]);
    expect(searching.result.current.servers.map((entry) => entry.key)).toEqual([
      "hubspot",
      "linear",
      "zendesk",
    ]);
    expect(searching.result.current.servers[0]?.name).toBe("CRM again");
  });

  it("takes a connected app's logo and address from the catalog it is listed in", () => {
    state.curated = [server("hubspot", "CRM")];

    const { result } = renderHook(() => useMcpAppStep({ connection_id: "c2", tool: "find" }));

    expect(result.current?.app.icon).toBe("hubspot");
    expect(result.current?.app.url).toBe("https://hubspot.example.com");
  });
});

describe("useMcpAppStep", () => {
  it("retains a registry service's logo after the picker search is closed", () => {
    state.entry = {
      key: "hubspot",
      name: "CRM",
      description: "",
      category: "productivity",
      auth: "oauth",
      url: "https://mcp.example.com",
      icon: "crm",
      docs_url: null,
      token_hint: null,
    };
    const { result } = renderHook(() => useMcpAppStep({ connection_id: "c2", tool: "find" }));
    expect(result.current?.app.url).toBe(state.entry.url);
    expect(result.current?.app.icon).toBe("crm");
  });
  it("finds the app of an MCP call's connection, with the tool it names", () => {
    const { result } = renderHook(() =>
      useMcpAppStep({ connection_id: "c1", tool: "draft_gmail_message" }),
    );
    expect(result.current?.app.id).toBe("gmail");
    expect(result.current?.tool).toBe("draft_gmail_message");
  });

  it("groups a tool by its name, and has no app for a sign-in tool", () => {
    const calendar = renderHook(() => useMcpAppStep({ connection_id: "c1", tool: "get_events" }));
    expect(calendar.result.current?.app.id).toBe("google_calendar");
    const signIn = renderHook(() =>
      useMcpAppStep({ connection_id: "c1", tool: "start_google_auth" }),
    );
    expect(signIn.result.current).toBeNull();
  });

  it("has no tool yet before one is chosen", () => {
    const { result } = renderHook(() => useMcpAppStep({ connection_id: "c1" }));
    expect(result.current?.tool).toBe("");
  });

  it("names a custom server as its own app and refuses an unknown connection", () => {
    const unclaimed = renderHook(() => useMcpAppStep({ connection_id: "c2", tool: "x" }));
    const unknown = renderHook(() => useMcpAppStep({ connection_id: "gone", tool: "x" }));
    expect(unclaimed.result.current?.app.name).toBe("crm");
    expect(unknown.result.current).toBeNull();

    state.canRead = false;
    const hidden = renderHook(() => useMcpAppStep({ connection_id: "c1", tool: "x" }));
    expect(hidden.result.current).toBeNull();
  });
});

describe("refreshing workflow MCP tools", () => {
  it("invalidates the shared inventory after probing and propagates a refusal", async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useRefreshWorkflowMcpTools(), {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });
    probe.mockResolvedValueOnce({ error: null, tools: [] });
    await act(() => result.current.mutateAsync("c1"));
    expect(probe).toHaveBeenCalledWith("c1");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.mcpConnections.all() });
    probe.mockResolvedValueOnce({ error: "Connection refused" });
    await act(async () => {
      await expect(result.current.mutateAsync("c1")).rejects.toThrow("Connection refused");
    });
    expect(result.current.isError).toBe(true);
  });
});
