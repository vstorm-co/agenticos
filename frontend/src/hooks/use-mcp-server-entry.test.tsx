import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type { McpCatalogEntry } from "@/types/mcp";
import { useMcpServerEntry } from "./use-mcp-servers";

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

beforeEach(() => vi.mocked(apiClient.get).mockReset());

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

  it("looks nothing up without a key", async () => {
    answer([entry("notion")], []);

    const { result } = renderHook(() => useMcpServerEntry(null), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.entry).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalledWith(expect.stringContaining("/agents/mcp-servers"));
  });
});
