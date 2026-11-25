import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import { useAuthStore, useOrgStore } from "@/stores";
import type { AppConnection } from "@/types/app-connections";
import { useConnectionHealth } from "./use-connection-health";

const listMcpConnections = vi.fn();
const listOrgMcpConnections = vi.fn();
const listAppConnections = vi.fn();
const can = vi.fn<(permission: string) => boolean>(() => false);

vi.mock("@/lib/mcp-connections-api", () => ({
  listMcpConnections: (...args: unknown[]) => listMcpConnections(...args),
}));
vi.mock("@/lib/org-mcp-connections-api", () => ({
  listOrgMcpConnections: (...args: unknown[]) => listOrgMcpConnections(...args),
}));
vi.mock("@/lib/app-connections-api", () => ({
  listAppConnections: (...args: unknown[]) => listAppConnections(...args),
}));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can }) }));

function personal(overrides: Partial<McpConnectionRecord> = {}): McpConnectionRecord {
  return {
    id: "p1",
    name: "github",
    url: "https://api.githubcopilot.com/mcp/",
    has_auth_token: true,
    allowed_tools: null,
    is_enabled: true,
    include_instructions: false,
    trust_read_only_hints: false,
    auth_type: "bearer",
    oauth_authorized: false,
    authorized: true,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    visibility: "org",
    catalog_key: null,
    is_default: false,
    label: null,
    last_tools: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function organization(overrides: Partial<OrgMcpConnectionRecord> = {}): OrgMcpConnectionRecord {
  return { ...personal(), id: "o1", catalog_key: "github", granted_scopes: null, ...overrides };
}

function app(overrides: Partial<AppConnection> = {}): AppConnection {
  return {
    id: "a1",
    catalog_key: "github",
    toolkit: "github",
    name: "GitHub",
    label: null,
    identity: null,
    status: "connected",
    is_enabled: true,
    is_default: false,
    authorized: true,
    readiness: "authorization_verified",
    last_checked_at: null,
    last_error: null,
    created_at: "2026-07-01T00:00:00Z",
    app: {
      key: "github",
      toolkit: "github",
      name: "GitHub",
      description: "Read issues and pull requests.",
      category: "development",
      configured: true,
      availability: "ready",
      approval_required: true,
      action_count: 3,
      actions: [],
    },
    ...overrides,
  };
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { wrapper };
}

beforeEach(() => {
  vi.clearAllMocks();
  can.mockReturnValue(false);
  useAuthStore.setState({
    user: {
      id: "user-1",
      email: "one@example.test",
      is_active: true,
      created_at: "2026-01-01",
    },
  });
  useOrgStore.setState({ activeOrgId: "org-1" });
  listMcpConnections.mockResolvedValue([]);
  listOrgMcpConnections.mockResolvedValue([]);
  listAppConnections.mockResolvedValue([]);
});

describe("useConnectionHealth", () => {
  it("reports zero when every connection is healthy", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useConnectionHealth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current).toMatchObject({ apps: 0, mcp: 0, total: 0 });
  });

  it("counts personal and organization trouble in the sidebar total", async () => {
    can.mockImplementation((permission) => permission === "mcp:manage");
    listMcpConnections.mockResolvedValue([personal({ authorized: false })]);
    listOrgMcpConnections.mockResolvedValue([organization({ id: "o2", last_status: "error" })]);
    const { wrapper } = setup();
    const { result } = renderHook(() => useConnectionHealth(), { wrapper });
    await waitFor(() => expect(result.current.total).toBe(2));
    expect(result.current).toMatchObject({ apps: 0, mcp: 2, total: 2 });
  });

  it("does not ask for the organization's list without mcp:manage", async () => {
    // A Member holds no manage permission; the backend would 403, which is a
    // truer thing to avoid than to show as an empty list.
    const { wrapper } = setup();
    const { result } = renderHook(() => useConnectionHealth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(listOrgMcpConnections).not.toHaveBeenCalled();
    expect(result.current).toMatchObject({ apps: 0, mcp: 0, total: 0 });
  });

  it("counts an expired app once even though it is also a personal connection", async () => {
    listMcpConnections.mockResolvedValue([
      personal({ id: "shared", auth_type: "composio", authorized: false }),
    ]);
    listAppConnections.mockResolvedValue([
      app({ id: "shared", status: "expired", authorized: false }),
    ]);
    const { wrapper } = setup();
    const { result } = renderHook(() => useConnectionHealth(), { wrapper });
    await waitFor(() => expect(result.current.total).toBe(1));
    expect(result.current).toMatchObject({ apps: 1, mcp: 1, total: 1 });
  });
});
