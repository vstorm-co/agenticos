import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCreatedToast } from "./use-created-toast";
import { qk } from "@/lib/query-keys";
import { useAddToAgentStore, useOrgStore } from "@/stores";

vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function holding(...permissions: string[]) {
  client.setQueryData(qk.organizations.permissions("o1"), {
    permissions: permissions.map((permission) => ({ permission, scope: "all" })),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient();
  useOrgStore.setState({ activeOrgId: "o1" });
  useAddToAgentStore.setState({ offer: null });
});

describe("the toast after creating something (#2072)", () => {
  it("offers to add it to an agent, for somebody who may edit agents", () => {
    holding("agents:edit");
    const { result } = renderHook(() => useCreatedToast(), { wrapper });

    result.current("Skill created", { kind: "skill", id: "s1" }, "refunds");

    const [message, options] = vi.mocked(toast.success).mock.calls[0]!;
    expect(message).toBe("Skill created");
    const action = (options as { action: { label: string; onClick: () => void } }).action;
    expect(action.label).toBe("Add to an agent");
    action.onClick();
    expect(useAddToAgentStore.getState().offer).toEqual({
      resource: { kind: "skill", id: "s1" },
      name: "refunds",
    });
  });

  it("just says so to anybody else, and before permissions are known", () => {
    holding("agents:view");
    const { result } = renderHook(() => useCreatedToast(), { wrapper });
    result.current("Skill created", { kind: "skill", id: "s1" }, "refunds");

    useOrgStore.setState({ activeOrgId: null });
    const unknown = renderHook(() => useCreatedToast(), { wrapper });
    unknown.result.current("Skill created", { kind: "skill", id: "s1" }, "refunds");

    expect(vi.mocked(toast.success).mock.calls).toEqual([["Skill created"], ["Skill created"]]);
  });
});
