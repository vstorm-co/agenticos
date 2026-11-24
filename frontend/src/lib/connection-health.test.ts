import { describe, expect, it } from "vitest";

import type { McpConnectionRecord } from "./mcp-connections-api";
import type { OrgMcpConnectionRecord } from "./org-mcp-connections-api";
import {
  appConnectionNeedsAttention,
  connectionHealthCounts,
  mcpConnectionNeedsAttention,
} from "./connection-health";
import type { AppConnection } from "@/types/app-connections";

function personal(overrides: Partial<McpConnectionRecord> = {}): McpConnectionRecord {
  return {
    id: "p1",
    name: "github",
    url: "https://api.githubcopilot.com/mcp/",
    has_auth_token: true,
    allowed_tools: null,
    is_enabled: true,
    include_instructions: false,
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

describe("mcpConnectionNeedsAttention", () => {
  it("flags a connection whose credential can no longer be used", () => {
    expect(mcpConnectionNeedsAttention(personal({ authorized: false }))).toBe(true);
  });

  it("flags a connection whose last probe failed", () => {
    expect(mcpConnectionNeedsAttention(personal({ last_status: "error" }))).toBe(true);
  });

  it("clears when the connection is healthy again", () => {
    expect(mcpConnectionNeedsAttention(personal())).toBe(false);
  });

  it("does not flag a connection somebody switched off on purpose", () => {
    expect(mcpConnectionNeedsAttention(personal({ is_enabled: false, last_status: "error" }))).toBe(
      false,
    );
  });

  it("does not flag a connection nobody has probed yet", () => {
    expect(mcpConnectionNeedsAttention(personal({ last_status: null }))).toBe(false);
  });
});

describe("appConnectionNeedsAttention", () => {
  it("flags an expired account", () => {
    expect(appConnectionNeedsAttention(app({ status: "expired", authorized: false }))).toBe(true);
  });

  it("flags a failed account", () => {
    expect(appConnectionNeedsAttention(app({ status: "failed", authorized: false }))).toBe(true);
  });

  it("clears when the account is connected again", () => {
    expect(appConnectionNeedsAttention(app())).toBe(false);
  });

  it("does not flag an account somebody disabled on purpose", () => {
    expect(
      appConnectionNeedsAttention(
        app({ is_enabled: false, status: "disabled", authorized: false }),
      ),
    ).toBe(false);
  });
});

describe("connectionHealthCounts", () => {
  it("counts nothing when everything is healthy", () => {
    expect(connectionHealthCounts([personal()], [organization()], [app()])).toEqual({
      apps: 0,
      mcp: 0,
      total: 0,
    });
  });

  it("counts personal and organization trouble separately, and totals both", () => {
    const counts = connectionHealthCounts(
      [personal({ authorized: false })],
      [organization({ id: "o2", last_status: "error" })],
      [app()],
    );
    expect(counts).toEqual({ apps: 0, mcp: 2, total: 2 });
  });

  it("counts an expired app once, not once per list it appears in", () => {
    // An app account is the same row as a personal MCP connection: the Apps
    // tab and the MCP tab both show it, and the sidebar must not count it
    // twice for being on both.
    const expired = app({ id: "shared", status: "expired", authorized: false });
    const counts = connectionHealthCounts(
      [personal({ id: "shared", auth_type: "composio", authorized: false })],
      [],
      [expired],
    );
    expect(counts).toEqual({ apps: 1, mcp: 1, total: 1 });
  });

  it("counts an app-only failure in the total even where the MCP list is empty", () => {
    // The two lists load independently; a failure in one must not hide a
    // failure the other already knows about.
    const counts = connectionHealthCounts([], [], [app({ status: "failed", authorized: false })]);
    expect(counts).toEqual({ apps: 1, mcp: 0, total: 1 });
  });
});
