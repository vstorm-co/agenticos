import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SKILL_CHECK_POLL_MS, useOpenSkillCheck, useSkillCheck } from "./use-skill-check";
import * as api from "@/lib/skill-checks-api";
import type { SkillCheck } from "@/types/skill-checks";

vi.mock("@/lib/skill-checks-api", () => ({
  cancelSkillCheck: vi.fn(),
  listSkillChecks: vi.fn(),
  estimateSkillCheck: vi.fn(),
  startSkillCheck: vi.fn(),
  getSkillCheck: vi.fn(),
  applySkillCheck: vi.fn(),
  discardSkillCheck: vi.fn(),
}));

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("useSkillCheck", () => {
  it("reads nothing before a check exists", () => {
    const { result } = renderHook(() => useSkillCheck("s-1", null), { wrapper });

    expect(result.current.check).toBeNull();
    expect(api.getSkillCheck).not.toHaveBeenCalled();
  });

  it("reads a check, and the skill and its waiting changes again once it is decided", async () => {
    vi.mocked(api.getSkillCheck).mockResolvedValue({ id: "c-1", status: "done" } as SkillCheck);
    vi.mocked(api.applySkillCheck).mockResolvedValue({});
    vi.mocked(api.discardSkillCheck).mockResolvedValue({} as SkillCheck);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSkillCheck("s-1", "c-1"), { wrapper });

    await waitFor(() => expect(result.current.check?.id).toBe("c-1"));
    await act(() => result.current.apply.mutateAsync({ acknowledge_unknown: true }));
    await act(() => result.current.discard.mutateAsync());

    expect(api.applySkillCheck).toHaveBeenCalledWith("s-1", "c-1", { acknowledge_unknown: true });
    expect(api.discardSkillCheck).toHaveBeenCalledWith("s-1", "c-1");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["skill-changes"] });
  });

  it("reads a running check again until it finishes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.getSkillCheck).mockResolvedValue({ id: "c-1", status: "running" } as SkillCheck);
    renderHook(() => useSkillCheck("s-1", "c-1"), { wrapper });

    await waitFor(() => expect(api.getSkillCheck).toHaveBeenCalledTimes(1));
    await act(() => vi.advanceTimersByTimeAsync(SKILL_CHECK_POLL_MS));

    await waitFor(() => expect(api.getSkillCheck).toHaveBeenCalledTimes(2));
    vi.useRealTimers();
  });

  it("finds the open check of one change, and stops a running one", async () => {
    vi.mocked(api.listSkillChecks).mockResolvedValue([
      { id: "c-old", proposal_id: "p-1", status: "applied" },
      { id: "c-other", proposal_id: "p-2", status: "running" },
      { id: "c-open", proposal_id: "p-1", status: "done" },
    ] as SkillCheck[]);
    vi.mocked(api.cancelSkillCheck).mockResolvedValue({} as SkillCheck);
    const open = renderHook(() => useOpenSkillCheck("s-1", null, "p-1"), { wrapper });
    const none = renderHook(() => useOpenSkillCheck("s-1", "f-1", "p-9"), { wrapper });
    const { result } = renderHook(() => useSkillCheck("s-1", "c-open"), { wrapper });

    await waitFor(() => expect(open.result.current.data?.id).toBe("c-open"));
    await waitFor(() => expect(none.result.current.data).toBeNull());
    await act(() => result.current.cancel.mutateAsync());
    expect(api.cancelSkillCheck).toHaveBeenCalledWith("s-1", "c-open");
  });

  it("prices and starts through the skill", async () => {
    vi.mocked(api.estimateSkillCheck).mockResolvedValue({} as SkillCheck);
    vi.mocked(api.startSkillCheck).mockResolvedValue({ id: "c-2" } as SkillCheck);
    const { result } = renderHook(() => useSkillCheck("s-1", null), { wrapper });
    const body = { fork_id: null, proposal_id: "p-1" };

    await act(() => result.current.estimate.mutateAsync(body));
    await act(() => result.current.start.mutateAsync(body));

    expect(api.estimateSkillCheck).toHaveBeenCalledWith("s-1", body);
    expect(api.startSkillCheck).toHaveBeenCalledWith("s-1", body);
  });
});
