import { describe, expect, it, vi } from "vitest";

import { toolsForBinding } from "./binding-tools";
import type { OrgMcpConnectionRecord } from "./org-mcp-connections-api";

function connection(overrides: Partial<OrgMcpConnectionRecord> = {}): OrgMcpConnectionRecord {
  return {
    id: "c1",
    name: "notion",
    url: "https://mcp.notion.com/mcp",
    has_auth_token: true,
    allowed_tools: null,
    is_enabled: true,
    auth_type: "oauth",
    oauth_authorized: true,
    last_status: null,
    last_error: null,
    last_checked_at: null,
    catalog_key: "notion",
    is_default: false,
    label: null,
    last_tools: null,
    granted_scopes: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

const SEARCH = { name: "search", description: "Search pages." };

describe("toolsForBinding", () => {
  it("probes a connection nobody has checked and opens with what it found", async () => {
    // The picker used to open empty and send the person to the servers page to
    // press Check; the Builder can press it for them.
    const probe = vi.fn().mockResolvedValue({ ok: true, error: null, tools: [SEARCH] });

    const { connection: probed, error } = await toolsForBinding(connection(), probe);

    expect(probe).toHaveBeenCalledWith("c1");
    expect(probed.last_tools).toEqual([SEARCH]);
    expect(error).toBeNull();
  });

  it("leaves a probed connection alone rather than dialling out again", async () => {
    const probe = vi.fn();
    const already = connection({ last_tools: [SEARCH] });

    const result = await toolsForBinding(already, probe);

    expect(probe).not.toHaveBeenCalled();
    expect(result).toEqual({ connection: already, error: null });
  });

  it("does not probe for a caller who may not, and says nothing", async () => {
    // `connections:manage` gates the probe; an agent author without it gets the
    // empty catalogue and the dialog's sentence about the servers page.
    const result = await toolsForBinding(connection(), null);

    expect(result).toEqual({ connection: connection(), error: null });
  });

  it("hands back the probe's refusal and the connection as it was", async () => {
    const probe = vi.fn().mockResolvedValue({ ok: false, error: "401 from the server", tools: [] });

    const { connection: unchanged, error } = await toolsForBinding(connection(), probe);

    expect(unchanged.last_tools).toBeNull();
    expect(error).toBe("401 from the server");
  });
});
