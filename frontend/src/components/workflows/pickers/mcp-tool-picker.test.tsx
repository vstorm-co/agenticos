import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { qk } from "@/lib/query-keys";
import type { UsableMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

import { McpConnectionPicker, McpToolField, useMcpToolSchema } from "./mcp-tool-picker";

vi.mock("./workflow-connections-dialog", () => ({
  WorkflowConnectionsDialog: ({ onOpenChange }: { onOpenChange: (open: boolean) => void }) => (
    <button onClick={() => onOpenChange(false)}>Account setup</button>
  ),
}));

const state = vi.hoisted(() => ({
  canManage: true,
  canEdit: true,
  connections: [] as UsableMcpConnectionRecord[],
  isLoading: false,
  test: vi.fn(),
  invalidate: vi.fn(),
}));
const toast = vi.hoisted(() => ({ error: vi.fn() }));

vi.mock("sonner", () => ({ toast }));
vi.mock("@/lib/org-mcp-connections-api", () => ({
  testOrgMcpConnection: (id: string) => state.test(id),
}));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => state.canManage }),
  useUsableMcpConnections: () => ({
    connections: state.canEdit ? state.connections : null,
    isLoading: state.isLoading,
    canRead: state.canEdit,
  }),
  useMcpCatalog: () => ({
    servers: [{ key: "hubspot", url: "https://mcp.hubspot.com", icon: "hubspot" }],
  }),
}));
vi.mock("@/components/mcp/mcp-server-icon", () => ({
  McpServerIcon: ({ icon, name }: { icon: string | null | undefined; name: string }) => (
    <span data-testid="mark">{`${icon ?? "monogram"}:${name}`}</span>
  ),
}));

const connection = (overrides: Partial<UsableMcpConnectionRecord>) =>
  ({
    id: "c1",
    name: "hubspot",
    label: "HubSpot",
    catalog_key: "hubspot",
    is_enabled: true,
    last_tools: [
      { name: "find_contact", description: "Look a contact up" },
      { name: "create_contact", description: "" },
    ],
    ...overrides,
  }) as UsableMcpConnectionRecord;

beforeEach(() => {
  state.canManage = true;
  state.canEdit = true;
  state.connections = [connection({})];
  state.isLoading = false;
  state.test.mockReset();
  state.invalidate.mockReset();
  toast.error.mockReset();
});

function renderField(props: Partial<Parameters<typeof McpToolField>[0]> = {}) {
  const onChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.spyOn(client, "invalidateQueries").mockImplementation(state.invalidate);
  render(
    <QueryClientProvider client={client}>
      <McpToolField connectionId="c1" tool={null} onChange={onChange} {...props} />
    </QueryClientProvider>,
  );
  return onChange;
}

describe("McpToolField", () => {
  it("shows each server with its service's mark and its label", async () => {
    state.connections = [
      connection({}),
      connection({
        id: "c2",
        name: "custom",
        label: null,
        catalog_key: null,
        is_enabled: false,
      }),
    ];
    const onChange = renderField({ connectionId: null });

    await userEvent.click(screen.getByRole("combobox", { name: "MCP server" }));

    expect(screen.getAllByText("hubspot:HubSpot")[0]).toBeInTheDocument();
    expect(screen.getByText("monogram:custom")).toBeInTheDocument();
    expect(screen.getByText("off")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: /custom/ }));
    expect(onChange).toHaveBeenCalledWith({ connectionId: "c2", tool: null });
  });

  it("offers the tools the server listed, and choosing one keeps the server", async () => {
    const onChange = renderField();

    await userEvent.click(screen.getByRole("combobox", { name: "Tool" }));
    expect(screen.getByText("Look a contact up")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: /create_contact/ }));

    expect(onChange).toHaveBeenCalledWith({ connectionId: "c1", tool: "create_contact" });
  });

  it("offers only tools permitted by the connection allowlist", async () => {
    state.connections = [connection({ allowed_tools: ["find_contact"] })];
    renderField();
    await userEvent.click(screen.getByRole("combobox", { name: "Tool" }));
    expect(screen.getByRole("option", { name: /find_contact/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /create_contact/ })).not.toBeInTheDocument();
  });

  it("keeps a tool the list no longer has as the choice shown", () => {
    renderField({ tool: "retired_tool" });

    expect(screen.getByRole("combobox", { name: "Tool" })).toHaveTextContent("retired_tool");
  });

  it("asks for a test of a server nobody has tested, and refreshes on request", async () => {
    state.connections = [connection({ last_tools: null })];
    state.test.mockResolvedValue({ ok: true, error: null, tools: [] });
    renderField();

    expect(screen.getByText(/Nobody has tested this server yet/)).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Tool" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Refresh tools" }));

    expect(state.test).toHaveBeenCalledWith("c1");
    // The list the picker reads is read again, so the new tools show.
    expect(state.invalidate).toHaveBeenCalledWith({ queryKey: qk.mcpConnections.all() });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("says why a refresh failed, whether the server answered or not", async () => {
    state.test.mockResolvedValueOnce({ ok: false, error: "401 Unauthorized", tools: [] });
    state.test.mockRejectedValueOnce(new Error("down"));
    renderField();

    await userEvent.click(screen.getByRole("button", { name: "Refresh tools" }));
    await userEvent.click(screen.getByRole("button", { name: "Refresh tools" }));

    expect(toast.error).toHaveBeenNthCalledWith(1, "401 Unauthorized");
    expect(toast.error).toHaveBeenNthCalledWith(2, "Could not reach the server.");
  });

  it("asks for no tool until a server is chosen, and shows each field's problem", () => {
    renderField({ connectionId: null, serverError: "Pick a server" });

    expect(screen.queryByRole("combobox", { name: "Tool" })).toBeNull();
    expect(screen.getByText("Pick a server")).toBeVisible();
  });

  it("opens account setup without leaving the step when no server is connected", async () => {
    state.connections = [];
    renderField({ toolError: "unused" });

    expect(screen.getByText(/The server this step names is gone/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Connect account" }));
    expect(screen.getByRole("button", { name: "Account setup" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Account setup" }));
    expect(screen.queryByRole("button", { name: "Account setup" })).toBeNull();
  });

  it("shows the tool's problem under the tool", () => {
    renderField({ toolError: "The server did not offer this tool" });

    expect(screen.getByText("The server did not offer this tool")).toBeVisible();
  });

  it("tells a member who may not edit this workflow why there is no list", () => {
    state.canEdit = false;
    renderField();

    expect(screen.getByText(/can't edit this workflow/)).toBeVisible();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("lets an editor who does not manage servers pick a server and a tool, with no way to add or test one", async () => {
    state.canManage = false;
    state.connections = [connection({}), connection({ id: "c2", name: "nope", last_tools: null })];
    const onChange = renderField();

    await userEvent.click(screen.getByRole("combobox", { name: "Tool" }));
    await userEvent.click(screen.getByRole("option", { name: /find_contact/ }));

    expect(onChange).toHaveBeenCalledWith({ connectionId: "c1", tool: "find_contact" });
    expect(screen.queryByRole("button", { name: "Refresh tools" })).toBeNull();
  });

  it("offers an editor who cannot manage servers no Connect link when there are none", () => {
    state.canManage = false;
    state.connections = [];
    renderField({ connectionId: null });

    expect(screen.queryByRole("button", { name: "Connect account" })).toBeNull();
  });

  it("tells an editor who cannot test a server to ask a manager", () => {
    state.canManage = false;
    state.connections = [connection({ last_tools: null })];
    renderField();

    expect(screen.getByText(/Ask someone who manages the organization's servers/)).toBeVisible();
  });
});

describe("McpConnectionPicker", () => {
  it("writes the chosen server", async () => {
    const onChange = vi.fn();
    render(<McpConnectionPicker value={null} onChange={onChange} error="Required" />);

    await userEvent.click(screen.getByRole("combobox", { name: "MCP server" }));
    await userEvent.click(screen.getByRole("option", { name: /HubSpot/ }));

    expect(onChange).toHaveBeenCalledWith("c1");
    expect(screen.getByText("Required")).toBeVisible();
  });

  it("tells a member who may not edit this workflow why there is no list", () => {
    state.canEdit = false;
    render(<McpConnectionPicker value={null} onChange={vi.fn()} />);

    expect(screen.getByText(/can't edit this workflow/)).toBeVisible();
  });

  it("lists the servers for an editor without mcp:manage", async () => {
    state.canManage = false;
    render(<McpConnectionPicker value={null} onChange={vi.fn()} />);

    await userEvent.click(screen.getByRole("combobox", { name: "MCP server" }));

    expect(screen.getByRole("option", { name: /HubSpot/ })).toBeVisible();
  });
});

describe("useMcpToolSchema", () => {
  const schema = { type: "object", properties: { email: { type: "string" } } };

  it("selects schemas only among the connection's allowed tools", () => {
    state.connections = [
      connection({
        allowed_tools: ["other"],
        last_tools: [
          { name: "find_contact", description: "", input_schema: { type: "string" } },
          { name: "other", description: "", input_schema: schema },
        ],
      }),
    ];
    const { result } = renderHook(() => useMcpToolSchema("c1", "other"));
    expect(result.current).toEqual(schema);
  });

  it("reads the chosen tool's argument schema for an editor who does not manage servers", () => {
    state.canManage = false;
    state.connections = [
      connection({ last_tools: [{ name: "find_contact", description: "", input_schema: schema }] }),
    ];
    const { result } = renderHook(() => useMcpToolSchema("c1", "find_contact"));
    expect(result.current).toEqual(schema);
  });

  it("is null for a tool the list has no schema for, and for somebody who may not edit", () => {
    expect(renderHook(() => useMcpToolSchema("c1", "other")).result.current).toBeNull();
    state.canEdit = false;
    expect(renderHook(() => useMcpToolSchema("c1", "find_contact")).result.current).toBeNull();
  });
});
