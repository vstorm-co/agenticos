import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SKILL_CHECK_POLL_MS,
  useOpenSkillCheck,
  useSkillCheck,
  useSkillCheckHistory,
  useSkillChecksAwaiting,
} from "./use-skill-check";
import * as api from "@/lib/skill-checks-api";
import type { SkillCheck } from "@/types/skill-checks";

vi.mock("@/lib/skill-checks-api", () => ({
  cancelSkillCheck: vi.fn(),
  estimateSkillCheck: vi.fn(),
  startSkillCheck: vi.fn(),
  getSkillCheck: vi.fn(),
  listSkillChecks: vi.fn(),
  applySkillCheck: vi.fn(),
  discardSkillCheck: vi.fn(),
  forkSkillCheck: vi.fn(),
  listSkillChecksAwaiting: vi.fn(),
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
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["agents"] });
  });

  it("reads a check again each time it is shown, however recently it was read", async () => {
    client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 5 * 60 * 1000 } },
    });
    vi.mocked(api.getSkillCheck).mockResolvedValue({ id: "c-1", status: "done" } as SkillCheck);
    const first = renderHook(() => useSkillCheck("s-1", "c-1"), { wrapper });
    await waitFor(() => expect(first.result.current.check?.id).toBe("c-1"));
    first.unmount();

    renderHook(() => useSkillCheck("s-1", "c-1"), { wrapper });

    await waitFor(() => expect(api.getSkillCheck).toHaveBeenCalledTimes(2));
  });

  it("reads the check and the skill again when a decision is refused", async () => {
    vi.mocked(api.applySkillCheck).mockRejectedValue(new Error("gone"));
    vi.mocked(api.discardSkillCheck).mockRejectedValue(new Error("gone"));
    vi.mocked(api.forkSkillCheck).mockRejectedValue(new Error("gone"));
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSkillCheck("s-1", "c-1"), { wrapper });

    for (const decide of [
      () => result.current.apply.mutateAsync({}),
      () => result.current.discard.mutateAsync(),
      () => result.current.fork.mutateAsync({ name: "Prints" }),
    ]) {
      await act(() => decide().catch(() => undefined));
    }

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["skill-checks", "s-1"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["skills", "s-1"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["skill-checks", "awaiting"] });
    expect(invalidate).toHaveBeenCalledTimes(9);
  });

  it("makes a fork of a check, then reads what it moved", async () => {
    vi.mocked(api.forkSkillCheck).mockResolvedValue({});
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSkillCheck("s-1", "c-1"), { wrapper });

    await act(() => result.current.fork.mutateAsync({ name: "Prints", agent_ids: ["a-1"] }));

    expect(api.forkSkillCheck).toHaveBeenCalledWith("s-1", "c-1", {
      name: "Prints",
      agent_ids: ["a-1"],
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["agents"] });
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

  it("stops a running check", async () => {
    vi.mocked(api.cancelSkillCheck).mockResolvedValue({} as SkillCheck);
    const { result } = renderHook(() => useSkillCheck("s-1", "c-open"), { wrapper });

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

describe("useOpenSkillCheck", () => {
  const check = (overrides: Partial<SkillCheck>) =>
    ({ id: "c", status: "done", session_id: null, ...overrides }) as SkillCheck;

  it("finds the check left to come back to, and reads it again while it runs", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.listSkillChecks).mockResolvedValue({
      items: [
        check({ id: "in-session", status: "running", session_id: "s" }),
        check({ id: "applied", status: "applied" }),
        check({ id: "catch-up", status: "done", source: "catch_up" }),
        check({ id: "open", status: "running" }),
      ],
      total: 3,
    });
    const { result } = renderHook(() => useOpenSkillCheck("s-1", "f-1"), { wrapper });

    await waitFor(() => expect(result.current.check?.id).toBe("open"));
    expect(api.listSkillChecks).toHaveBeenCalledWith("s-1", "f-1", 0);
    await act(() => vi.advanceTimersByTimeAsync(SKILL_CHECK_POLL_MS));
    expect(api.listSkillChecks).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("has nothing to come back to once every check is decided", async () => {
    vi.mocked(api.listSkillChecks).mockResolvedValue({
      items: [check({ status: "discarded" })],
      total: 1,
    });
    const { result } = renderHook(() => useOpenSkillCheck("s-1", null), { wrapper });

    await waitFor(() => expect(api.listSkillChecks).toHaveBeenCalled());
    expect(result.current.check).toBeNull();
  });

  it("says when the line's checks could not be read", async () => {
    vi.mocked(api.listSkillChecks).mockRejectedValue(new Error("checks offline"));
    const { result } = renderHook(() => useOpenSkillCheck("s-1", null), { wrapper });

    await waitFor(() => expect(result.current.error).toBeInstanceOf(Error));
    expect(result.current.check).toBeNull();
  });
});

describe("useSkillCheckHistory", () => {
  it("lists a line's checks, newest first, with how many there are", async () => {
    vi.mocked(api.listSkillChecks).mockResolvedValue({
      items: [{ id: "c-2", status: "discarded" } as SkillCheck],
      total: 7,
    });
    const { result } = renderHook(() => useSkillCheckHistory("s-1", null, 0), { wrapper });

    await waitFor(() => expect(result.current.checks?.[0]?.id).toBe("c-2"));
    expect(result.current.total).toBe(7);
  });

  it("reads the page asked for", async () => {
    vi.mocked(api.listSkillChecks).mockResolvedValue({ items: [], total: 45 });
    renderHook(() => useSkillCheckHistory("s-1", "f-1", 2), { wrapper });

    await waitFor(() => expect(api.listSkillChecks).toHaveBeenCalledWith("s-1", "f-1", 2));
  });

  it("counts nothing before the list is read", () => {
    vi.mocked(api.listSkillChecks).mockReturnValue(new Promise(() => undefined));
    const { result } = renderHook(() => useSkillCheckHistory("s-1", null, 0), { wrapper });

    expect(result.current.total).toBe(0);
    expect(result.current.isLoading).toBe(true);
  });
});

describe("useSkillChecksAwaiting", () => {
  it("lists the open checks and reads them again while one runs", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.listSkillChecksAwaiting).mockResolvedValue([
      { id: "c-1", status: "running" },
    ] as Awaited<ReturnType<typeof api.listSkillChecksAwaiting>>);
    const { result } = renderHook(() => useSkillChecksAwaiting(), { wrapper });

    await waitFor(() => expect(result.current.checks).toHaveLength(1));
    await act(() => vi.advanceTimersByTimeAsync(SKILL_CHECK_POLL_MS));
    expect(api.listSkillChecksAwaiting).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("stops reading once none runs, and reads nothing when told not to", async () => {
    vi.mocked(api.listSkillChecksAwaiting).mockResolvedValue([
      { id: "c-1", status: "done" },
    ] as Awaited<ReturnType<typeof api.listSkillChecksAwaiting>>);
    const { result } = renderHook(() => useSkillChecksAwaiting(), { wrapper });
    await waitFor(() => expect(result.current.checks).toHaveLength(1));

    vi.mocked(api.listSkillChecksAwaiting).mockClear();
    const off = renderHook(() => useSkillChecksAwaiting({ enabled: false }), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
      ),
    });
    expect(off.result.current.checks).toEqual([]);
    expect(api.listSkillChecksAwaiting).not.toHaveBeenCalled();
  });
});
