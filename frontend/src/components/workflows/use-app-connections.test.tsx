import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { UsableMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

import { useAppConnections, useMcpAppStep } from "./use-app-connections";

const gmail = { id: "c1", name: "gmail-dev", label: null, catalog_key: "google-workspace" };
const other = { id: "c2", name: "crm", label: null, catalog_key: "hubspot" };

const state = vi.hoisted(() => ({
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
    expect(result.current).toEqual({ connections: null, canConnect: true, unavailable: false });
  });

  it("reports it unavailable where the workflow cannot be edited", () => {
    state.canRead = false;
    const { result } = renderHook(() => useAppConnections());
    expect(result.current).toEqual({ connections: null, canConnect: true, unavailable: true });
  });
});

describe("useMcpAppStep", () => {
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

  it("is null for a connection no app claims, an unknown one, and while the list is unknown", () => {
    const unclaimed = renderHook(() => useMcpAppStep({ connection_id: "c2", tool: "x" }));
    const unknown = renderHook(() => useMcpAppStep({ connection_id: "gone", tool: "x" }));
    expect(unclaimed.result.current).toBeNull();
    expect(unknown.result.current).toBeNull();

    state.canRead = false;
    const hidden = renderHook(() => useMcpAppStep({ connection_id: "c1", tool: "x" }));
    expect(hidden.result.current).toBeNull();
  });
});
