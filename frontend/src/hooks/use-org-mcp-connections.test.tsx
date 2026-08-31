import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOrgMcpConnections } from "./use-org-mcp-connections";
import { apiClient } from "@/lib/api-client";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function record(overrides: Partial<OrgMcpConnectionRecord> = {}): OrgMcpConnectionRecord {
  return {
    id: "c1",
    name: "github",
    url: "https://api.githubcopilot.com/mcp/",
    has_auth_token: true,
    allowed_tools: null,
    is_enabled: true,
    auth_type: "bearer",
    oauth_authorized: false,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    catalog_key: "github",
    is_default: false,
    label: null,
    last_tools: null,
    granted_scopes: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

async function loaded() {
  const hook = renderHook(() => useOrgMcpConnections(), { wrapper });
  await waitFor(() => expect(hook.result.current.isLoading).toBe(false));
  return hook;
}

describe("useOrgMcpConnections", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [record()], total: 1 });
  });

  it("reads the organization's servers, not the caller's own", async () => {
    // The two endpoints return the same shape, so calling the wrong one fails
    // no type check and no render - it just quietly puts one member's private
    // credentials in front of every agent author in the organization.
    const { result } = await loaded();

    expect(apiClient.get).toHaveBeenCalledWith("/mcp-connections");
    expect(result.current.connections.map((connection) => connection.id)).toEqual(["c1"]);
  });

  it("keeps the credential out of the record it caches", async () => {
    const { result } = await loaded();

    const connection = result.current.connections[0];
    expect(connection?.has_auth_token).toBe(true);
    expect(JSON.stringify(connection)).not.toContain('auth_token":"');
  });

  it("adds a created server to the list without a refetch", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(record({ id: "c2", name: "linear" }));
    const { result } = await loaded();

    await act(async () => {
      await result.current.create({ name: "linear", url: "https://mcp.linear.app/sse" });
    });

    await waitFor(() =>
      expect(result.current.connections.map((connection) => connection.name)).toEqual([
        "github",
        "linear",
      ]),
    );
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("drops a removed server from the list", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = await loaded();

    await act(async () => {
      await result.current.remove("c1");
    });

    await waitFor(() => expect(result.current.connections).toEqual([]));
  });

  it("refetches after a check, because the check writes the status it does not return", async () => {
    // The probe response carries tools and an error, never the row. Trusting it
    // would leave a red dot next to a server that just answered.
    vi.mocked(apiClient.post).mockResolvedValue({ ok: true, error: null, tools: [] });
    const { result } = await loaded();

    await act(async () => {
      await result.current.test("c1");
    });

    expect(apiClient.post).toHaveBeenCalledWith("/mcp-connections/c1/test");
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("reports a refusal rather than showing an empty organization", async () => {
    // A member without connections:manage gets a 403. An empty list would read
    // as "your organization has connected nothing", which is a different and
    // wrong thing to tell somebody about to build an agent.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Insufficient permissions"));

    const { result } = await loaded();

    expect(result.current.error).toBe("Insufficient permissions");
    expect(result.current.connections).toEqual([]);
  });

  it("patches an edited server in place", async () => {
    // The list is the page; a refetch would blank the row somebody is editing.
    vi.mocked(apiClient.patch).mockResolvedValue(record({ is_enabled: false }));
    const { result } = await loaded();

    await act(async () => {
      await result.current.update("c1", { is_enabled: false });
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/mcp-connections/c1", { is_enabled: false });
    await waitFor(() => expect(result.current.connections[0]?.is_enabled).toBe(false));
  });

  it("refreshes on demand", async () => {
    const { result } = await loaded();

    await act(async () => {
      await result.current.refresh();
    });

    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("falls back to its own sentence when the refusal carries none", async () => {
    vi.mocked(apiClient.get).mockRejectedValue("boom");

    const { result } = renderHook(() => useOrgMcpConnections(), { wrapper });

    await waitFor(() =>
      expect(result.current.error).toBe("Failed to load the organization's MCP servers"),
    );
  });

  it("says nothing went wrong when nothing did", async () => {
    const { result } = await loaded();

    expect(result.current.error).toBeNull();
  });
});
