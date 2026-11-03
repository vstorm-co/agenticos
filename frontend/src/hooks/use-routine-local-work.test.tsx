import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRoutineLocalWork } from "./use-routine-local-work";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import type { DeviceStatus } from "@/lib/desktop/commands";
import type { ShellInfo } from "@/lib/desktop/shell";

const bridge = vi.hoisted(() => ({
  list: vi.fn(),
  allow: vi.fn(),
  pick: vi.fn(),
  revoke: vi.fn(),
  report: vi.fn(),
}));
let shell: ShellInfo | null;
let device: DeviceStatus | undefined;
vi.mock("@/lib/desktop/commands", () => ({
  getLocalState: vi.fn(async () => ({ grants: [], modes: ["read_only", "workspace_write"] })),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => shell }));
vi.mock("@/hooks/use-desktop", () => ({ useDeviceStatus: () => ({ data: device }) }));
vi.mock("@/lib/desktop/routine-work", () => ({
  listRoutineGrants: bridge.list,
  allowRoutine: bridge.allow,
  chooseRoutineFolder: bridge.pick,
  revokeRoutineGrant: bridge.revoke,
}));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: bridge.report,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  shell = { platform: "macos", version: "1", window: "main", vibrancy: false };
  device = {
    linked: true,
    connected: true,
    identity: { user_id: "owner", device_id: "device", origin: "https://example.com" },
  };
  useAuthStore.setState({
    user: {
      id: "owner",
      email: "owner@example.com",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
    },
  });
  useOrgStore.setState({ activeOrgId: "org" });
  bridge.list.mockResolvedValue([]);
  bridge.pick.mockResolvedValue(null);
  bridge.allow.mockResolvedValue(null);
  bridge.revoke.mockResolvedValue(undefined);
});
describe("routine local consent", () => {
  it("reads only this paired owner's organization and refreshes after revocation", async () => {
    const { result } = renderHook(() => useRoutineLocalWork(), { wrapper });
    await waitFor(() => expect(result.current.grants.isSuccess).toBe(true));
    expect(bridge.list).toHaveBeenCalledWith("org", "owner");
    await act(async () => {
      await result.current.revoke.mutateAsync("grant");
    });
    expect(bridge.revoke).toHaveBeenCalledWith("grant", "org", "owner");
    await waitFor(() => expect(bridge.list).toHaveBeenCalledTimes(2));
  });
  it.each(["browser", "mobile", "unpaired", "other-owner", "no-user", "no-org"])(
    "does not read native grants in %s",
    async (state) => {
      if (state === "browser") shell = null;
      if (state === "mobile")
        shell = { platform: "ios", version: "1", window: "main", vibrancy: false };
      if (state === "unpaired") device = undefined;
      if (state === "other-owner")
        device = {
          linked: true,
          connected: true,
          identity: { user_id: "another", device_id: "device", origin: "https://example.com" },
        };
      if (state === "no-user") useAuthStore.setState({ user: null });
      if (state === "no-org") useOrgStore.setState({ activeOrgId: null });
      const { result } = renderHook(() => useRoutineLocalWork(), { wrapper });
      expect(result.current.available).toBe(false);
      expect(bridge.list).not.toHaveBeenCalled();
      await act(async () => {
        await expect(result.current.revoke.mutateAsync("grant")).rejects.toThrow(
          "No paired routine owner",
        );
      });
      await act(async () => {
        await result.current.grants.refetch();
      });
      expect(bridge.list).not.toHaveBeenCalled();
      expect(bridge.revoke).not.toHaveBeenCalled();
      expect(toast.error).toHaveBeenCalled();
    },
  );
  it("reports refusal without hiding it as successful permission", async () => {
    bridge.pick.mockRejectedValue(new Error("refused"));
    const { result } = renderHook(() => useRoutineLocalWork(), { wrapper });
    await act(async () => {
      await expect(result.current.pick.mutateAsync()).rejects.toThrow("refused");
    });
    expect(bridge.report).toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });
  it("preserves cancellation and invalidates the native inventory after consent", async () => {
    const { result } = renderHook(() => useRoutineLocalWork(), { wrapper });
    await waitFor(() => expect(result.current.grants.isSuccess).toBe(true));
    const request = {
      organization_id: "org",
      user_id: "owner",
      device_id: "device",
      routine_id: "routine",
      name: "Report",
      root: "/work",
      operations: { read: true as const, write: false, execute: false },
    };
    await act(async () => {
      expect(await result.current.allow.mutateAsync(request)).toBeNull();
    });
    expect(bridge.allow).toHaveBeenCalledWith(request, expect.anything());
    await waitFor(() => expect(bridge.list).toHaveBeenCalledTimes(2));
  });
  it("surfaces inventory read failures", async () => {
    bridge.list.mockRejectedValue(new Error("corrupt native store"));
    const { result } = renderHook(() => useRoutineLocalWork(), { wrapper });
    await waitFor(() => expect(result.current.grants.isError).toBe(true));
    expect(result.current.grants.data).toBeUndefined();
  });
});
