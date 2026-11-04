import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { staleQueries } from "@/lib/live-updates";
import type { McpCatalogEntry } from "@/types/mcp";
import { useMcpCatalogPage, useMcpServerEntry } from "./use-mcp-servers";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

/**
 * The server a chat's connection card names by key (#2301): the curated
 * catalog when it holds it, else the mirrored registry, which it does not.
 */

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function entry(key: string): McpCatalogEntry {
  return {
    key,
    name: key,
    description: "",
    category: "productivity",
    auth: "oauth",
    url: `https://${key}.example/mcp`,
    docs_url: null,
    token_hint: null,
    icon: null,
  };
}

function answer(curated: McpCatalogEntry[], listed: McpCatalogEntry[]) {
  vi.mocked(apiClient.get).mockImplementation((url: string) =>
    Promise.resolve(
      url === "/agents/mcp-catalog"
        ? { items: curated, total: curated.length }
        : { items: listed, total: listed.length },
    ),
  );
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
});

describe("useMcpServerEntry", () => {
  it("takes a curated server from the catalog, without searching", async () => {
    answer([entry("notion")], []);

    const { result } = renderHook(() => useMcpServerEntry("notion"), { wrapper });

    await waitFor(() => expect(result.current.entry?.key).toBe("notion"));
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("finds a mirrored server by searching for its key", async () => {
    answer([entry("notion")], [entry("com.mintmcp/gmail-drafts"), entry("com.mintmcp/gmail")]);

    const { result } = renderHook(() => useMcpServerEntry("com.mintmcp/gmail"), { wrapper });

    expect(result.current).toEqual({ entry: null, isLoading: true });
    await waitFor(() => expect(result.current.entry?.key).toBe("com.mintmcp/gmail"));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/agents/mcp-servers?q=com.mintmcp%2Fgmail&limit=10",
    );
  });

  it("settles on nothing for a key neither knows", async () => {
    answer([], [entry("com.mintmcp/gmail")]);

    const { result } = renderHook(() => useMcpServerEntry("made-up"), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.entry).toBeNull();
  });

  it.each(["unreachable", "broken", "refused", "duplicate"] as const)(
    "finds a saved %s server excluded from catalog browsing",
    async (outcome) => {
      const saved = {
        ...entry("com.example/saved"),
        connection_ids: ["account-1"],
        check: { outcome, checked_at: "2026-11-03T00:00:00Z", tools: null, read_only_tools: null },
      };
      vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
        const items = path.includes("state=connected") ? [saved] : [];
        return { items, total: items.length };
      });

      const { result } = renderHook(() => useMcpServerEntry(saved.key), { wrapper });

      await waitFor(() => expect(result.current.entry).toEqual(saved));
      expect(result.current.isLoading).toBe(false);
    },
  );

  it("looks nothing up without a key", async () => {
    answer([entry("notion")], []);

    const { result } = renderHook(() => useMcpServerEntry(null), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.entry).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalledWith(expect.stringContaining("/agents/mcp-servers"));
  });

  it("refreshes connected results, counts and bookmarked accounts after a remote connection change", async () => {
    const custom = { ...entry("custom-server"), custom: true, connection_ids: ["account-1"] };
    let listed: McpCatalogEntry[] = [custom];
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      const items = path === "/agents/mcp-catalog" ? [] : listed;
      return { items, total: items.length };
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(
      () => ({
        listing: useMcpCatalogPage("", "", "", 0, true, "connected"),
        bookmarked: useMcpServerEntry("custom-server"),
      }),
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );
    await waitFor(() => {
      expect(result.current.listing.total).toBe(1);
      expect(result.current.bookmarked.entry?.connection_ids).toEqual(["account-1"]);
    });

    listed = [
      { ...custom, connection_ids: ["account-2"] },
      { ...entry("another-server"), connection_ids: ["account-3"] },
    ];
    await act(async () => {
      await Promise.all(
        staleQueries({
          organization_id: "org-1",
          resource: "mcp_connection",
          id: "account-2",
          action: "updated",
          surface: "mcp",
          actor_user_id: "another-user",
          actor_name: "Ada",
          origin_tab: null,
        }).map((queryKey) => client.invalidateQueries({ queryKey })),
      );
    });

    await waitFor(() => {
      expect(result.current.listing.total).toBe(2);
      expect(result.current.listing.servers.map((server) => server.key)).toEqual([
        "custom-server",
        "another-server",
      ]);
      expect(result.current.bookmarked.entry?.connection_ids).toEqual(["account-2"]);
    });
  });
});
