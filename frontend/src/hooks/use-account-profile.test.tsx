import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const patch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", () => ({ apiClient: { patch } }));

import { useSaveAgentContext, useSaveProactiveOptOut } from "./use-account-profile";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";

beforeEach(() => {
  patch.mockReset();
  useAuthStore.setState({ user: { id: "u-1", job_title: null } as User });
});

describe("useSaveAgentContext", () => {
  it("saves on the account and keeps the session's copy in step with the answer", async () => {
    const saved = { id: "u-1", job_title: "Sales" } as User;
    patch.mockResolvedValue(saved);
    const { result } = renderHook(() => useSaveAgentContext());

    await expect(result.current({ job_title: "Sales" })).resolves.toBe(saved);

    expect(patch).toHaveBeenCalledWith("/users/me", { job_title: "Sales" });
    expect(useAuthStore.getState().user?.job_title).toBe("Sales");
  });

  it("leaves the session's copy alone when the save is refused", async () => {
    patch.mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useSaveAgentContext());

    await expect(result.current({ job_title: "Sales" })).rejects.toThrow("nope");
    expect(useAuthStore.getState().user?.job_title).toBeNull();
  });
});

describe("useSaveProactiveOptOut", () => {
  it("leaves the person out of the nightly look, and the session knows it", async () => {
    const saved = { id: "u-1", job_title: null, proactive_opt_out: true } as User;
    patch.mockResolvedValue(saved);
    const { result } = renderHook(() => useSaveProactiveOptOut());

    await expect(result.current(true)).resolves.toBe(saved);

    expect(patch).toHaveBeenCalledWith("/users/me", { proactive_opt_out: true });
    expect(useAuthStore.getState().user?.proactive_opt_out).toBe(true);
  });
});
