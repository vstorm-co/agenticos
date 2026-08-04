import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSkillChanges } from "./use-skill-changes";
import * as api from "@/lib/skill-changes-api";
import type { SkillChangeRecord } from "@/lib/skill-changes-api";

vi.mock("@/lib/skill-changes-api", () => ({
  listSkillChanges: vi.fn(),
  applySkillChange: vi.fn(),
  discardSkillChange: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function change(overrides: Partial<SkillChangeRecord> = {}): SkillChangeRecord {
  return {
    id: "p-1",
    skill_id: "s-1",
    agent_id: "a-1",
    conversation_id: "c-1",
    name: "refunds",
    description: "How refunds work now.",
    content: "Ask for the receipt.",
    resources: {},
    status: "pending",
    decided_by_user_id: null,
    decided_at: null,
    created_at: "2026-08-03T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listSkillChanges).mockResolvedValue([change()]);
  vi.mocked(api.applySkillChange).mockResolvedValue(change({ status: "applied" }));
  vi.mocked(api.discardSkillChange).mockResolvedValue(change({ status: "discarded" }));
});

describe("useSkillChanges", () => {
  it("asks for the pending ones by default, because those are the decisions", async () => {
    const { result } = renderHook(() => useSkillChanges(), { wrapper });

    await waitFor(() => expect(result.current.changes).toHaveLength(1));
    expect(api.listSkillChanges).toHaveBeenCalledWith("pending");
  });

  it("accepting refetches, because the skill it rewrote moved too", async () => {
    // A skills page left showing the old body would be showing something no
    // agent is following any more.
    const { result } = renderHook(() => useSkillChanges(), { wrapper });
    await waitFor(() => expect(result.current.changes).toHaveLength(1));

    await act(async () => {
      await result.current.apply("p-1");
    });

    expect(api.applySkillChange).toHaveBeenCalledWith("p-1");
    await waitFor(() => expect(api.listSkillChanges).toHaveBeenCalledTimes(2));
  });

  it("refusing refetches too", async () => {
    const { result } = renderHook(() => useSkillChanges(), { wrapper });
    await waitFor(() => expect(result.current.changes).toHaveLength(1));

    await act(async () => {
      await result.current.discard("p-1");
    });

    expect(api.discardSkillChange).toHaveBeenCalledWith("p-1");
    await waitFor(() => expect(api.listSkillChanges).toHaveBeenCalledTimes(2));
  });

  it("reports a refused second decision rather than swallowing it", async () => {
    // The server refuses it with a 409; a silent failure here would leave a
    // reviewer believing they had applied something.
    const { toast } = await import("sonner");
    const refused = new Error("This change was already applied.");
    vi.mocked(api.applySkillChange).mockRejectedValue(refused);
    const { result } = renderHook(() => useSkillChanges(), { wrapper });
    await waitFor(() => expect(result.current.changes).toHaveLength(1));

    await expect(
      act(async () => {
        await result.current.apply("p-1");
      }),
    ).rejects.toThrow(refused);

    expect(toast.error).toHaveBeenCalledWith("This change was already applied.");
  });

  it("reports a refusal to discard as well", async () => {
    const { toast } = await import("sonner");
    vi.mocked(api.discardSkillChange).mockRejectedValue(new Error("already discarded"));
    const { result } = renderHook(() => useSkillChanges(), { wrapper });
    await waitFor(() => expect(result.current.changes).toHaveLength(1));

    await expect(
      act(async () => {
        await result.current.discard("p-1");
      }),
    ).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("already discarded");
  });

  it("says why the list is empty rather than leaving it looking like nothing pending", async () => {
    vi.mocked(api.listSkillChanges).mockRejectedValue(new Error("403 Forbidden"));
    const { result } = renderHook(() => useSkillChanges(), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("403 Forbidden"));
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(api.listSkillChanges).mockRejectedValue("nope");
    const { result } = renderHook(() => useSkillChanges(), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Failed to load proposed skill changes"));
  });
});
