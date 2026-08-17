import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usePortals } from "./use-portals";
import { apiClient } from "@/lib/api-client";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PORTALS = {
  items: [
    {
      key: "github",
      name: "GitHub",
      description: "Run an agent when something happens in a repository.",
      category: "development",
      icon: "github",
      event_source: "github",
      delivery: "auto_webhook",
      target_kind: "repo",
      connection_catalog_key: "github",
      presets: [
        { key: "issue_opened", label: "New issue", description: "…", target_required: true },
      ],
    },
    {
      key: "email",
      name: "Email",
      description: "Run an agent when an email arrives.",
      category: "productivity",
      icon: "gmail",
      event_source: "email",
      delivery: "manual",
      target_kind: null,
      connection_catalog_key: null,
      presets: [{ key: "any_email", label: "Any email", description: "…", target_required: false }],
    },
  ],
  total: 2,
};

const MCP_CATALOG = {
  items: [
    {
      key: "github",
      name: "GitHub",
      description: "Read issues.",
      category: "development",
      auth: "oauth",
      url: "https://api.githubcopilot.com/mcp/",
      docs_url: null,
      token_hint: null,
      icon: "github",
    },
  ],
  total: 1,
};

function orgConnection(overrides: Partial<OrgMcpConnectionRecord> = {}): OrgMcpConnectionRecord {
  return {
    id: "o1",
    name: "github",
    url: "https://api.githubcopilot.com/mcp/",
    has_auth_token: false,
    allowed_tools: null,
    is_enabled: true,
    auth_type: "oauth",
    oauth_authorized: true,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    catalog_key: "github",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function serve(org: OrgMcpConnectionRecord[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/trigger-portals") return PORTALS;
    if (path === "/agents/mcp-catalog") return MCP_CATALOG;
    if (path === "/mcp-connections") return { items: org, total: org.length };
    if (path === "/me/mcp-connections") return { items: [], total: 0 };
    throw new Error(`unexpected GET ${path}`);
  });
}

async function run(org: OrgMcpConnectionRecord[] = []) {
  serve(org);
  const { result } = renderHook(() => usePortals(), { wrapper });
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  return result;
}

describe("usePortals", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks an auto-webhook portal with no connection to connect the account", async () => {
    const result = await run([]);
    const github = result.current.items.find((item) => item.portal.key === "github");
    expect(github?.action).toBe("connect");
    expect(github?.connection).toBeNull();
  });

  it("joins the portal to its shared MCP connection by connection_catalog_key", async () => {
    const result = await run([orgConnection()]);
    const github = result.current.items.find((item) => item.portal.key === "github");
    // Connected and authorized → ready to create, carrying the joined connection
    // and the shared server's URL for a later re-authorization.
    expect(github?.action).toBe("create");
    expect(github?.connection?.id).toBe("o1");
    expect(github?.serverUrl).toBe("https://api.githubcopilot.com/mcp/");
  });

  it("asks to re-authorize when the connection has not finished consent", async () => {
    // An OAuth connection awaiting consent is the closest signal the API exposes
    // to "the webhook scope is missing" - the same re-consent repairs both.
    const result = await run([orgConnection({ oauth_authorized: false })]);
    const github = result.current.items.find((item) => item.portal.key === "github");
    expect(github?.action).toBe("reauthorize");
  });

  it("lets a manual portal create a trigger with no connection at all", async () => {
    const result = await run([]);
    const email = result.current.items.find((item) => item.portal.key === "email");
    expect(email?.action).toBe("create");
    expect(email?.connection).toBeNull();
  });
});
