import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ToolPickerState } from "@/components/mcp/mcp-server-list-types";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import type { AgentSpec, McpServerRef } from "@/types/agents";

import { McpBindingsEditor, toolChoice } from "./mcp-bindings-editor";

const state = vi.hoisted(() => ({
  canManage: true,
  probe: vi.fn(),
  toolsForBinding: vi.fn(),
  picker: null as ToolPickerState | null,
  setPicker: null as ((next: ToolPickerState | null) => void) | null,
  onSave: null as (() => void) | null,
  connected: null as ((connection: OrgMcpConnectionRecord) => void) | null,
  closeConnect: null as (() => void) | null,
  connecting: null as unknown,
  connectingOwn: null as unknown,
  closeOwn: null as (() => void) | null,
  enableSearch: null as (() => void) | null,
  signIn: vi.fn(),
}));
const toast = vi.hoisted(() => ({ error: vi.fn() }));

vi.mock("sonner", () => ({ toast }));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => state.canManage }),
  useOrgMcpConnections: () => ({ connections: [], test: state.probe }),
  useMcpCatalog: () => ({ servers: [] }),
  useMcpConnections: () => ({ connections: [] }),
}));
vi.mock("@/lib/mcp-oauth", () => ({ hereForMcpOAuthReturn: () => "/agents/a1" }));
vi.mock("@/components/agents/mcp-tool-load-notice", () => ({
  McpToolLoadNotice: ({ onEnableToolSearch }: { onEnableToolSearch: () => void }) => {
    state.enableSearch = onEnableToolSearch;
    return null;
  },
}));
vi.mock("@/lib/binding-tools", () => ({ toolsForBinding: state.toolsForBinding }));

const connection = (lastTools: { name: string; description: string }[] | null) =>
  ({ id: "c1", last_tools: lastTools }) as unknown as OrgMcpConnectionRecord;
const ref: McpServerRef = {
  account: "organization",
  connection_id: "c1",
  allowed_tools: null,
  approval: "none",
};
const specWith = (mcp_servers: McpServerRef[]) =>
  ({ mcp_servers, capabilities: [] }) as unknown as AgentSpec;

vi.mock("@/components/agents/mcp-server-picker", () => ({
  bindingKey: (binding: McpServerRef) => JSON.stringify(binding),
  McpServerPicker: ({
    onTools,
    onConnect,
    onConnectOwn,
    onSignInOwn,
  }: {
    onConnectOwn: (entry: unknown) => void;
    onSignInOwn: (connection: unknown) => void;
    onTools: (ref: McpServerRef, probed: OrgMcpConnectionRecord, name: string) => Promise<void>;
    onConnect: (entry: unknown) => void;
  }) => (
    <div>
      <button
        type="button"
        onClick={() => void onTools(ref, connection([{ name: "a", description: "" }]), "Notion")}
      >
        tools
      </button>
      <button type="button" onClick={() => onConnect({ key: "notion" })}>
        connect
      </button>
      <button type="button" onClick={() => onConnectOwn({ key: "notion" })}>
        connect-own
      </button>
      <button type="button" onClick={() => onSignInOwn({ id: "p1" })}>
        sign-in-own
      </button>
    </div>
  ),
}));
vi.mock("@/components/mcp/mcp-tool-picker-dialog", () => ({
  McpToolPickerDialog: ({
    toolPicker,
    setToolPicker,
    onSave,
  }: {
    toolPicker: ToolPickerState | null;
    setToolPicker: (next: ToolPickerState | null) => void;
    onSave: () => void;
  }) => {
    state.picker = toolPicker;
    state.setPicker = setToolPicker;
    state.onSave = onSave;
    return toolPicker ? <span>{`picker:${toolPicker.name}`}</span> : null;
  },
}));
vi.mock("@/components/agents/connect-server-dialog", () => ({
  ConnectServerDialog: ({
    entry,
    onClose,
    onConnected,
  }: {
    entry: unknown;
    onClose: () => void;
    onConnected: (connection: OrgMcpConnectionRecord) => void;
  }) => {
    state.connecting = entry;
    state.closeConnect = onClose;
    state.connected = onConnected;
    return null;
  },
  ConnectOwnServerDialog: ({ entry, onClose }: { entry: unknown; onClose: () => void }) => {
    state.connectingOwn = entry;
    state.closeOwn = onClose;
    return null;
  },
  // The real hook's OAuth branches are covered with the dialog; here it opens the form.
  useConnectEntry: (_scope: string, options: { openForm: (entry: unknown) => void }) =>
    options.openForm,
  useSignInOwn: () => state.signIn,
}));

beforeEach(() => {
  state.canManage = true;
  state.toolsForBinding.mockReset();
  state.picker = null;
  toast.error.mockReset();
});

describe("toolChoice", () => {
  it("opens on the last probe, every tool checked when the binding names none", () => {
    const choice = toolChoice(ref, connection([{ name: "a", description: "x" }]), "Notion");
    expect(choice.tools).toEqual([{ name: "a", description: "x" }]);
    expect([...choice.checked]).toEqual(["a"]);
    expect(choice.appliesTo).toBe("agent");
  });

  it("stands the binding's own names in for a server nothing has probed", () => {
    const choice = toolChoice({ ...ref, allowed_tools: ["b"] }, connection(null), "Notion");
    expect(choice.tools).toEqual([{ name: "b", description: "" }]);
    expect([...choice.checked]).toEqual(["b"]);
  });
});

describe("McpBindingsEditor", () => {
  it("narrows a server's tools into the binding, not the connection", async () => {
    state.toolsForBinding.mockResolvedValue({
      connection: connection([
        { name: "a", description: "" },
        { name: "b", description: "" },
      ]),
      error: null,
    });
    const onChange = vi.fn();
    render(<McpBindingsEditor spec={specWith([ref])} onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "tools" }));
    expect(state.toolsForBinding).toHaveBeenCalledWith(expect.anything(), state.probe);
    expect(screen.getByText("picker:Notion")).toBeVisible();
    act(() => state.setPicker?.({ ...state.picker!, checked: new Set(["a"]) }));
    act(() => state.onSave?.());

    expect(onChange).toHaveBeenLastCalledWith({ mcp_servers: [{ ...ref, allowed_tools: ["a"] }] });
    expect(screen.queryByText("picker:Notion")).toBeNull();
  });

  it("does not probe for somebody who may not manage connections, and says why it could not", async () => {
    state.canManage = false;
    state.toolsForBinding.mockResolvedValue({ connection: connection(null), error: "No list yet" });
    render(<McpBindingsEditor spec={specWith([ref])} onChange={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "tools" }));

    expect(state.toolsForBinding).toHaveBeenCalledWith(expect.anything(), null);
    expect(toast.error).toHaveBeenCalledWith("No list yet");
  });

  it("a probe that throws still opens the picker on what is known", async () => {
    state.toolsForBinding.mockRejectedValue(new Error("down"));
    render(<McpBindingsEditor spec={specWith([ref])} onChange={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "tools" }));

    expect(toast.error).toHaveBeenCalled();
    expect(screen.getByText("picker:Notion")).toBeVisible();
  });

  it("saving with no picker open changes nothing", () => {
    const onChange = vi.fn();
    render(<McpBindingsEditor spec={specWith([ref])} onChange={onChange} />);

    act(() => state.onSave?.());

    expect(onChange).not.toHaveBeenCalled();
  });

  it("binds a server connected on the spot and opens its tools", async () => {
    const onChange = vi.fn();
    render(<McpBindingsEditor spec={specWith([])} onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "connect" }));
    expect(state.connecting).toEqual({ key: "notion" });
    act(() =>
      state.connected?.({
        ...connection([{ name: "a", description: "" }]),
        id: "c9",
        name: "notion",
        label: "Notion",
      } as OrgMcpConnectionRecord),
    );
    act(() => state.closeConnect?.());

    expect(onChange).toHaveBeenCalledWith({
      mcp_servers: [
        { account: "organization", connection_id: "c9", allowed_tools: null, approval: "none" },
      ],
    });
    expect(screen.getByText("picker:Notion")).toBeVisible();
    expect(state.connecting).toBeNull();
  });

  it("falls back to the connection's name when it has no label", () => {
    render(<McpBindingsEditor spec={specWith([])} onChange={vi.fn()} />);

    act(() =>
      state.connected?.({
        ...connection(null),
        id: "c9",
        name: "notion",
        label: null,
      } as OrgMcpConnectionRecord),
    );

    expect(screen.getByText("picker:notion")).toBeVisible();
  });

  it("connects and signs in to the author's own account", async () => {
    render(<McpBindingsEditor spec={specWith([])} onChange={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "connect-own" }));
    expect(state.connectingOwn).toEqual({ key: "notion" });
    act(() => state.closeOwn?.());
    expect(state.connectingOwn).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "sign-in-own" }));
    expect(state.signIn).toHaveBeenCalledWith({ id: "p1" });
  });

  it("switches Tool search on from the load notice", () => {
    const onChange = vi.fn();
    render(<McpBindingsEditor spec={specWith([])} onChange={onChange} />);

    act(() => state.enableSearch?.());

    expect(onChange).toHaveBeenCalledWith({
      capabilities: [expect.objectContaining({ id: "tool_search" })],
    });
  });
});
