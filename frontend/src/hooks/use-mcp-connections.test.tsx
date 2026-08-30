import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMcpCatalog, useMcpServers } from "./use-mcp-servers";
import { useMcpConnections } from "./use-mcp-connections";
import { apiClient } from "@/lib/api-client";
import * as personalApi from "@/lib/mcp-connections-api";
import * as orgApi from "@/lib/org-mcp-connections-api";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
vi.mock("@/lib/mcp-connections-api", () => ({
  listMcpConnections: vi.fn(),
  createMcpConnection: vi.fn(),
  updateMcpConnection: vi.fn(),
  deleteMcpConnection: vi.fn(),
  testMcpConnection: vi.fn(),
}));
vi.mock("@/lib/org-mcp-connections-api", () => ({
  listOrgMcpConnections: vi.fn(),
  createOrgMcpConnection: vi.fn(),
  updateOrgMcpConnection: vi.fn(),
  deleteOrgMcpConnection: vi.fn(),
  testOrgMcpConnection: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function connection(overrides: Partial<McpConnectionRecord> = {}): McpConnectionRecord {
  return {
    id: "c-1",
    name: "linear",
    url: "https://mcp.linear.app/sse",
    has_auth_token: true,
    allowed_tools: null,
    is_enabled: true,
    auth_type: "bearer",
    oauth_authorized: false,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    catalog_key: null,
    is_default: false,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(personalApi.listMcpConnections).mockResolvedValue([connection()]);
  vi.mocked(orgApi.listOrgMcpConnections).mockResolvedValue([]);
});

async function personal() {
  const rendered = renderHook(() => useMcpConnections(), { wrapper });
  await waitFor(() => expect(rendered.result.current.isLoading).toBe(false));
  return rendered.result;
}

/**
 * A person's own MCP connections, and the catalog they are joined onto.
 *
 * The scope distinction is the point: `useMcpConnections` is one person's
 * credentials, `useOrgMcpConnections` is the organization's, and an agent may be
 * bound only to the second. `useMcpServers` joins both onto the catalog so one
 * page can answer "what exists, and who has connected it" - which is why the
 * *catalog's* and the *personal* failures are surfaced as the page's error and
 * the organization's is not: a member without `connections:manage` gets a 403
 * on the org list and can still read the rest.
 */
describe("a person's own connections", () => {
  it("reads their connections", async () => {
    const result = await personal();

    expect(result.current.connections).toHaveLength(1);
  });

  it("adds a created connection without a refetch", async () => {
    vi.mocked(personalApi.createMcpConnection).mockResolvedValue(connection({ id: "c-2" }));
    const result = await personal();

    await act(async () => {
      await result.current.create({ name: "crm", url: "https://crm/mcp" });
    });

    await waitFor(() =>
      expect(result.current.connections.map((row) => row.id)).toEqual(["c-1", "c-2"]),
    );
  });

  it("patches an edited connection in place", async () => {
    vi.mocked(personalApi.updateMcpConnection).mockResolvedValue(connection({ is_enabled: false }));
    const result = await personal();

    await act(async () => {
      await result.current.update("c-1", { is_enabled: false });
    });

    expect(personalApi.updateMcpConnection).toHaveBeenCalledWith("c-1", { is_enabled: false });
    await waitFor(() => expect(result.current.connections[0]?.is_enabled).toBe(false));
  });

  it("drops a removed connection", async () => {
    vi.mocked(personalApi.deleteMcpConnection).mockResolvedValue(undefined);
    const result = await personal();

    await act(async () => {
      await result.current.remove("c-1");
    });

    await waitFor(() => expect(result.current.connections).toEqual([]));
  });

  it("refetches after a check, because the check writes a status it does not return", async () => {
    vi.mocked(personalApi.testMcpConnection).mockResolvedValue({
      ok: true,
      error: null,
      tools: [],
    });
    const result = await personal();

    await act(async () => {
      await result.current.test("c-1");
    });

    expect(vi.mocked(personalApi.listMcpConnections).mock.calls.length).toBeGreaterThan(1);
  });

  it("refreshes on demand", async () => {
    const result = await personal();

    await act(async () => {
      await result.current.refresh();
    });

    expect(personalApi.listMcpConnections).toHaveBeenCalledTimes(2);
  });

  it("says what went wrong, and falls back when the failure says nothing", async () => {
    vi.mocked(personalApi.listMcpConnections).mockRejectedValue(new Error("Not authenticated"));
    const { result } = renderHook(() => useMcpConnections(), { wrapper });
    await waitFor(() => expect(result.current.error).toBe("Not authenticated"));

    vi.mocked(personalApi.listMcpConnections).mockRejectedValue("boom");
    const second = renderHook(() => useMcpConnections(), { wrapper });
    await waitFor(() => expect(second.result.current.error).toBe("Failed to load connections"));
  });

  it("says nothing went wrong when nothing did", async () => {
    const result = await personal();

    expect(result.current.error).toBeNull();
  });
});

describe("the curated catalog", () => {
  it("reads the deployment's catalog", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ key: "github" }] });

    const { result } = renderHook(() => useMcpCatalog(), { wrapper });

    await waitFor(() => expect(result.current.servers).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/mcp-catalog");
  });
});

describe("every server, with who has connected it", () => {
  it("joins the catalog onto both connection lists", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        {
          key: "github",
          name: "GitHub",
          description: "Issues and pull requests.",
          category: "development",
          auth: "token",
          url: "https://api.githubcopilot.com/mcp/",
          docs_url: null,
          token_hint: null,
          icon: null,
        },
      ],
    });
    vi.mocked(personalApi.listMcpConnections).mockResolvedValue([]);
    vi.mocked(orgApi.listOrgMcpConnections).mockResolvedValue([]);

    const { result } = renderHook(() => useMcpServers(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.rows.map((row) => row.key)).toEqual(["github"]);
  });

  it("reports the personal failure and not the organization's", async () => {
    // The org list needs `connections:manage`; surfacing its 403 as the page's
    // error would replace a usable screen with a refusal about one column of it.
    vi.mocked(orgApi.listOrgMcpConnections).mockRejectedValue(new Error("Forbidden"));
    vi.mocked(personalApi.listMcpConnections).mockResolvedValue([]);

    const { result } = renderHook(() => useMcpServers(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBeNull();
  });

  it("reports a failed catalog instead of drawing an empty deployment", async () => {
    // Without the catalog `mergeServers` yields [] with no error - "No servers"
    // on the one deployment state that cannot be true (it ships compiled in).
    vi.mocked(apiClient.get).mockRejectedValue(new Error("catalog down"));
    vi.mocked(personalApi.listMcpConnections).mockResolvedValue([]);
    vi.mocked(orgApi.listOrgMcpConnections).mockResolvedValue([]);

    const { result } = renderHook(() => useMcpServers(), { wrapper });

    await waitFor(() => expect(result.current.error).not.toBeNull());
  });

  it("remembers the tools a check discovered, keyed by connection", async () => {
    // Probe results are not a resource anyone can GET - they exist only as the
    // answer to a check somebody asked for, so they live outside the cache.
    const { result } = renderHook(() => useMcpServers(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() =>
      result.current.recordTools("c-1", [{ name: "create_issue", description: "Open an issue." }]),
    );

    expect(result.current.toolsByConnection).toEqual({
      "c-1": [{ name: "create_issue", description: "Open an issue." }],
    });
  });
});
