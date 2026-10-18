import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { McpCallLog } from "./mcp-call-log";
import type { McpConnectionRecord, McpToolCall } from "@/lib/mcp-connections-api";

const state = vi.hoisted(() => ({
  calls: [] as McpToolCall[],
  isLoading: false,
  error: null as unknown,
}));
vi.mock("@/hooks", () => ({ useOrgMcpToolCalls: () => state }));

const LEDGER = { id: "c1", name: "ledger", label: "Finance ledger" } as McpConnectionRecord;

function call(overrides: Partial<McpToolCall>): McpToolCall {
  return {
    tool: "search",
    status: "completed",
    started_at: new Date().toISOString(),
    duration_ms: 120,
    agent_id: "a1",
    agent_name: "Writer",
    run_id: "r1",
    ...overrides,
  };
}

describe("an MCP server's call log (#2072)", () => {
  it("lists each call: the tool, the agent, how it went, and its run", () => {
    state.calls = [
      call({}),
      call({ tool: "delete", status: "failed", agent_name: null, run_id: null, duration_ms: null }),
      call({ tool: "odd", status: "something-new" }),
    ];
    render(<McpCallLog connection={LEDGER} onClose={vi.fn()} />);

    expect(
      screen.getByRole("heading", { name: "What agents asked Finance ledger" }),
    ).toBeInTheDocument();
    expect(screen.getByText("done")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("something-new")).toBeInTheDocument();
    expect(screen.getByText(/The assistant/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Run" })[0]).toHaveAttribute("href", "/runs?run=r1");
  });

  it("says when nothing has called it, and loads, and fails", () => {
    state.calls = [];
    const { unmount } = render(<McpCallLog connection={LEDGER} onClose={vi.fn()} />);
    expect(screen.getByText("No agent has called this server yet.")).toBeInTheDocument();
    unmount();

    state.isLoading = true;
    const loading = render(<McpCallLog connection={LEDGER} onClose={vi.fn()} />);
    expect(screen.queryByText("No agent has called this server yet.")).toBeNull();
    loading.unmount();

    state.isLoading = false;
    state.error = new Error("boom");
    render(<McpCallLog connection={{ ...LEDGER, label: null }} onClose={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "What agents asked ledger" })).toBeInTheDocument();
    expect(screen.queryByText("No agent has called this server yet.")).toBeNull();
    state.error = null;
  });
});
