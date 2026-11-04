import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { UsableMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import { qk } from "@/lib/query-keys";

import { useUsableMcpConnections } from "./use-usable-mcp-connections";

const state = vi.hoisted(() => ({
  workflowId: "w1" as string | null,
  canEdit: true,
  detail: vi.fn(),
  list: vi.fn(),
}));
vi.mock("@/lib/workflows/workflows-api", () => ({
  getWorkflow: state.detail,
  listWorkflowMcpConnections: state.list,
}));
vi.mock("@/stores/workflow-editor-store", () => ({
  useWorkflowEditorStore: (select: (s: { workflowId: string | null }) => unknown) =>
    select({ workflowId: state.workflowId }),
}));

const gmail = { id: "c1", name: "gmail-dev" } as UsableMcpConnectionRecord;

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } });
  state.workflowId = "w1";
  state.detail.mockReset();
  state.list.mockReset();
  state.detail.mockImplementation(async () => ({ can_edit: state.canEdit }));
  state.list.mockResolvedValue([gmail]);
});

describe("useUsableMcpConnections", () => {
  it("lists the servers where the workflow's own can_edit is true, whatever the member's role", async () => {
    const { result } = renderHook(() => useUsableMcpConnections(), { wrapper });
    expect(result.current.connections).toBeNull();
    await waitFor(() => expect(result.current.connections).toEqual([gmail]));
    expect(result.current.canRead).toBe(true);
    expect(state.list).toHaveBeenCalledWith("w1");
  });

  it("asks nothing where the workflow cannot be edited, and says it is not known", async () => {
    state.canEdit = false;
    const { result } = renderHook(() => useUsableMcpConnections(), { wrapper });
    await waitFor(() => expect(state.detail).toHaveBeenCalled());
    expect(result.current).toMatchObject({ connections: null, canRead: false });
    expect(state.list).not.toHaveBeenCalled();
    state.canEdit = true;
  });

  it("asks nothing with no workflow open, or when told not to", () => {
    state.workflowId = null;
    renderHook(() => useUsableMcpConnections(), { wrapper });
    state.workflowId = "w1";
    renderHook(() => useUsableMcpConnections(false), { wrapper });
    expect(state.list).not.toHaveBeenCalled();
  });

  it("is stale at once, so a manager's new test shows without a reload", async () => {
    renderHook(() => useUsableMcpConnections(), { wrapper });
    await waitFor(() => expect(state.list).toHaveBeenCalledTimes(1));
    // The client's default would keep it fresh for a minute; this query overrides it.
    const query = client.getQueryCache().find({ queryKey: qk.mcpConnections.usable("w1") });
    expect(query?.isStale()).toBe(true);
    expect(query?.observers[0]?.options.refetchOnWindowFocus).toBe(true);
  });
});
