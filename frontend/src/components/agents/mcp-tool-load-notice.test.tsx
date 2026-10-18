import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { McpToolLoadNotice } from "./mcp-tool-load-notice";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import type { AgentSpec } from "@/types/agents";

const tools = (n: number) =>
  Array.from({ length: n }, (_, i) => ({ name: `tool_${i}`, description: "", read_only: true }));

function connection(toolCount: number): OrgMcpConnectionRecord {
  return { id: "o1", last_tools: tools(toolCount) } as OrgMcpConnectionRecord;
}

function spec(overrides: Partial<AgentSpec> = {}): AgentSpec {
  return {
    name: "Ops",
    instructions: "",
    model_settings: {},
    capabilities: [],
    collection_ids: [],
    skill_ids: [],
    context_ids: [],
    mcp_servers: [{ account: "organization", connection_id: "o1", allowed_tools: null }],
    ...overrides,
  } as AgentSpec;
}

describe("McpToolLoadNotice", () => {
  it("offers Tool search once the servers lay out more tools than the threshold", async () => {
    const enable = vi.fn();
    render(
      <McpToolLoadNotice
        spec={spec()}
        connections={[connection(45)]}
        personalConnections={[]}
        onEnableToolSearch={enable}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("45 tools");
    expect(screen.getByRole("status")).toHaveTextContent("18,000 tokens");
    await userEvent.click(screen.getByRole("button", { name: "Turn on Tool search" }));
    expect(enable).toHaveBeenCalledOnce();
  });

  it("says nothing at or under the threshold", () => {
    const { container } = render(
      <McpToolLoadNotice
        spec={spec()}
        connections={[connection(30)]}
        personalConnections={[]}
        onEnableToolSearch={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("says nothing once Tool search is on", () => {
    const { container } = render(
      <McpToolLoadNotice
        spec={spec({
          capabilities: [{ id: "tool_search", config: {} }] as AgentSpec["capabilities"],
        })}
        connections={[connection(80)]}
        personalConnections={[]}
        onEnableToolSearch={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("leaves the button to an editor", () => {
    render(
      <McpToolLoadNotice
        spec={spec()}
        connections={[connection(45)]}
        personalConnections={[]}
        onEnableToolSearch={vi.fn()}
        disabled
      />,
    );

    expect(screen.getByRole("button", { name: "Turn on Tool search" })).toBeDisabled();
  });
});
