import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMcpToolServers } from "./use-mcp-tool-servers";
import * as personalApi from "@/lib/mcp-connections-api";
import * as orgApi from "@/lib/org-mcp-connections-api";

vi.mock("@/lib/mcp-connections-api", () => ({ listMcpConnections: vi.fn() }));
vi.mock("@/lib/org-mcp-connections-api", () => ({ listOrgMcpConnections: vi.fn() }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(personalApi.listMcpConnections).mockResolvedValue([]);
  vi.mocked(orgApi.listOrgMcpConnections).mockResolvedValue([]);
});

/**
 * The servers a tool call can be named after.
 *
 * Nothing on a tool call says where it came from, so a step reads
 * `linear_create_issue` unless something matches that prefix against the connections
 * this caller can see. Both scopes, because an agent's spec can name either - and the
 * name and the URL are all a step needs: one for the label, one for the logo.
 */
describe("the MCP servers a step can be named after", () => {
  it("offers the organization's servers and the member's own", async () => {
    vi.mocked(orgApi.listOrgMcpConnections).mockResolvedValue([
      { id: "o-1", name: "Linear", url: "https://mcp.linear.app/sse" },
    ] as never);
    vi.mocked(personalApi.listMcpConnections).mockResolvedValue([
      { id: "p-1", name: "My GitHub", url: "https://api.github.com/mcp" },
    ] as never);

    const { result } = renderHook(() => useMcpToolServers(), { wrapper });

    await waitFor(() => expect(result.current).toHaveLength(2));
    // The organization's first: an agent's spec names one of those, and a member's own
    // connection sharing a name should not shadow it.
    expect(result.current.map((server) => server.name)).toEqual(["Linear", "My GitHub"]);
    expect(result.current[0]).toEqual({ name: "Linear", url: "https://mcp.linear.app/sse" });
  });

  it("answers with nothing rather than failing when neither list can be read", async () => {
    // A member who cannot list connections still has a readable transcript; the step
    // falls back to the humanised tool name.
    vi.mocked(orgApi.listOrgMcpConnections).mockRejectedValue(new Error("403 Forbidden"));
    vi.mocked(personalApi.listMcpConnections).mockRejectedValue(new Error("403 Forbidden"));

    const { result } = renderHook(() => useMcpToolServers(), { wrapper });

    await waitFor(() => expect(personalApi.listMcpConnections).toHaveBeenCalled());
    expect(result.current).toEqual([]);
  });
});
