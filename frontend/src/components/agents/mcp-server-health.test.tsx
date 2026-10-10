import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";

import { McpServerHealth } from "./mcp-server-health";
import { McpServerPicker } from "./mcp-server-picker";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

function server(overrides: Partial<OrgMcpConnectionRecord> = {}): OrgMcpConnectionRecord {
  return {
    id: "c1",
    name: "ledger",
    url: "https://ledger.example/mcp",
    has_auth_token: true,
    allowed_tools: null,
    is_enabled: true,
    auth_type: "bearer",
    oauth_authorized: false,
    authorized: true,
    last_status: "ok",
    last_error: null,
    last_checked_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    visibility: "org",
    catalog_key: null,
    is_default: false,
    label: null,
    last_tools: null,
    granted_scopes: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

describe("a bound MCP server's health in the Builder (#2072)", () => {
  it("says it answered and when", () => {
    render(<McpServerHealth connection={server({})} />);

    expect(screen.getByText("Answering - checked 5m ago")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check now" })).toBeNull();
  });

  it("says it stopped answering, why, and since when", () => {
    render(
      <McpServerHealth
        connection={server({ last_status: "error", last_error: "401 Unauthorized" })}
      />,
    );

    expect(screen.getByText("Not answering - checked 5m ago")).toBeInTheDocument();
    expect(screen.getByText("401 Unauthorized")).toBeInTheDocument();
  });

  it("says when nobody has checked it, or a failure has no time", () => {
    const { unmount } = render(<McpServerHealth connection={server({ last_checked_at: null })} />);
    expect(screen.getByText("Not checked yet")).toBeInTheDocument();
    unmount();

    render(
      <McpServerHealth connection={server({ last_status: "error", last_checked_at: null })} />,
    );
    expect(screen.getByText("Not answering")).toBeInTheDocument();
  });

  it("checks it again for whoever may, and says when the check itself failed", async () => {
    const onCheck = vi
      .fn()
      .mockResolvedValueOnce({ ok: true })
      .mockRejectedValueOnce(new Error("x"));
    render(<McpServerHealth connection={server({})} onCheck={onCheck} />);

    await userEvent.click(screen.getByRole("button", { name: "Check now" }));
    await userEvent.click(screen.getByRole("button", { name: "Check now" }));

    expect(onCheck).toHaveBeenCalledWith("c1");
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("sits under a server the agent is bound to through the organization's account", () => {
    render(
      <McpServerPicker
        connections={[server({})]}
        catalog={[]}
        value={[{ account: "organization", connection_id: "c1", allowed_tools: null }]}
        onChange={vi.fn()}
        onTools={vi.fn()}
        onConnect={vi.fn()}
        onCheck={vi.fn()}
      />,
    );

    expect(screen.getByText("Answering - checked 5m ago")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check now" })).toBeInTheDocument();
  });
});
