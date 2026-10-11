import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

import { McpConnectionPicker, McpToolField, useMcpToolSchema } from "./mcp-tool-picker";

const state = vi.hoisted(() => ({
  canManage: true,
  connections: [] as OrgMcpConnectionRecord[],
  isLoading: false,
  test: vi.fn(),
}));
const toast = vi.hoisted(() => ({ error: vi.fn() }));
const listed = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("sonner", () => ({ toast }));
vi.mock("@/lib/org-mcp-connections-api", () => ({ listOrgMcpConnections: listed.list }));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => state.canManage }),
  useOrgMcpConnections: () => ({
    connections: state.connections,
    isLoading: state.isLoading,
    test: state.test,
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

const connection = (overrides: Partial<OrgMcpConnectionRecord>) =>
  ({
    id: "c1",
    name: "hubspot",
    label: "HubSpot",
    url: "https://mcp.hubspot.com",
    is_enabled: true,
    last_tools: [
      { name: "find_contact", description: "Look a contact up" },
      { name: "create_contact", description: "" },
    ],
    ...overrides,
  }) as OrgMcpConnectionRecord;

beforeEach(() => {
  state.canManage = true;
  state.connections = [connection({})];
  state.isLoading = false;
  state.test.mockReset();
  toast.error.mockReset();
});

function renderField(props: Partial<Parameters<typeof McpToolField>[0]> = {}) {
  const onChange = vi.fn();
  render(<McpToolField connectionId="c1" tool={null} onChange={onChange} {...props} />);
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
        url: "https://x.example",
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

  it("names a server that is gone, and points to connecting one when there are none", () => {
    state.connections = [];
    renderField({ toolError: "unused" });

    expect(screen.getByText(/The server this step names is gone/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Connect one" })).toHaveAttribute(
      "href",
      "/mcp-servers",
    );
  });

  it("shows the tool's problem under the tool", () => {
    renderField({ toolError: "The server did not offer this tool" });

    expect(screen.getByText("The server did not offer this tool")).toBeVisible();
  });

  it("tells a member who may not manage servers why there is no list", () => {
    state.canManage = false;
    renderField();

    expect(screen.getByText(/needs mcp:manage/)).toBeVisible();
    expect(screen.queryByRole("combobox")).toBeNull();
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

  it("tells a member who may not manage servers why there is no list", () => {
    state.canManage = false;
    render(<McpConnectionPicker value={null} onChange={vi.fn()} />);

    expect(screen.getByText(/needs mcp:manage/)).toBeVisible();
  });
});

describe("useMcpToolSchema", () => {
  const schema = { type: "object", properties: { email: { type: "string" } } };

  function renderSchema(connectionId: string | null, tool: string | null) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return renderHook(() => useMcpToolSchema(connectionId, tool), {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });
  }

  beforeEach(() => {
    listed.list.mockReset();
    listed.list.mockResolvedValue([
      connection({ last_tools: [{ name: "find_contact", description: "", input_schema: schema }] }),
    ]);
  });

  it("reads the chosen tool's argument schema from the server's last list", async () => {
    const { result } = renderSchema("c1", "find_contact");

    await waitFor(() => expect(result.current).toEqual(schema));
  });

  it("is null for a tool the list has no schema for", async () => {
    const { result } = renderSchema("c1", "other");

    await waitFor(() => expect(listed.list).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });

  it("asks nothing before a server is chosen, or of somebody who may not list them", () => {
    renderSchema(null, null);
    state.canManage = false;
    const { result } = renderSchema("c1", "find_contact");

    expect(listed.list).not.toHaveBeenCalled();
    expect(result.current).toBeNull();
  });
});
