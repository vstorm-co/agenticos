import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOnboardingFlow } from "./use-onboarding-flow";
import { useOnboardingStore } from "@/stores";
import type { Permission } from "@/types/permissions";

// Mutable state the mocked hooks read, so a test can grow a list between renders.
const rig = vi.hoisted(() => ({
  skillTotal: 0,
  skillLoading: false,
  kbs: [] as unknown[],
  connections: [] as unknown[],
  orgs: [] as unknown[] | undefined,
  can: (_permission: Permission): boolean => true,
}));

vi.mock("@/hooks/use-skills", () => ({
  useSkills: () => ({ total: rig.skillTotal, isLoading: rig.skillLoading }),
}));
vi.mock("@/hooks/use-knowledge-bases", () => ({
  useKnowledgeBases: () => ({ kbs: rig.kbs, isLoading: false }),
}));
vi.mock("@/hooks/use-org-mcp-connections", () => ({
  useOrgMcpConnections: () => ({ connections: rig.connections, isLoading: false }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizationList: () => ({ data: rig.orgs, isLoading: false }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: rig.can, isLoading: false, error: null }),
}));

// One flow given a second, signal-less step so the advance-not-finish branch and
// the no-signal branch are both reachable — the real per-section flows are all a
// single step. The registry itself is covered by `flows.test.ts`.
vi.mock("@/lib/onboarding/flows", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/onboarding/flows")>("@/lib/onboarding/flows");
  return {
    ...actual,
    FLOWS: {
      ...actual.FLOWS,
      "create-kb": {
        id: "create-kb",
        steps: [
          {
            id: "kb-a",
            target: "knowledge-new",
            interactive: true,
            signal: { kind: "created", resource: "kb" },
          },
          { id: "kb-b", target: "knowledge-attach" },
        ],
      },
    },
  };
});

beforeEach(() => {
  rig.skillTotal = 0;
  rig.skillLoading = false;
  rig.kbs = [];
  rig.connections = [];
  rig.orgs = [];
  rig.can = () => true;
  useOnboardingStore.setState({ isOpen: false, index: 0, mode: "tour", flowId: null, offer: null });
});

describe("useOnboardingFlow", () => {
  it("is idle when no flow is running", () => {
    const { result } = renderHook(() => useOnboardingFlow());
    expect(result.current.isActive).toBe(false);
    expect(result.current.steps).toHaveLength(0);
    expect(result.current.step).toBeUndefined();
    expect(result.current.flowId).toBeNull();
  });

  it("runs the flow's steps the caller may perform", () => {
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    expect(result.current.isActive).toBe(true);
    expect(result.current.flowId).toBe("create-skill");
    expect(result.current.steps).toHaveLength(1);
    expect(result.current.step?.target).toBe("skills-new");
    expect(result.current.isLast).toBe(true);
  });

  it("is inactive when permissions filter every step away", () => {
    rig.can = () => false;
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    expect(result.current.steps).toHaveLength(0);
    expect(result.current.isActive).toBe(false);
  });

  it("meets the signal only once the resource list grows past where it began", () => {
    rig.skillTotal = 3; // three skills already exist
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    expect(result.current.signalMet).toBe(false);

    rig.skillTotal = 4; // the reader created one
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("does not mistake a list finishing its first load for a creation", () => {
    rig.skillLoading = true; // count unknown on the first frame
    const { result, rerender } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-skill"));
    expect(result.current.signalMet).toBe(false);

    rig.skillLoading = false;
    rig.skillTotal = 3; // 0 → 3 as the list settles is not "created three"
    rerender();
    expect(result.current.signalMet).toBe(false);

    rig.skillTotal = 4;
    rerender();
    expect(result.current.signalMet).toBe(true);
  });

  it("advances through a multi-step flow and ends after the last", () => {
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-kb"));
    expect(result.current.index).toBe(0);

    act(() => result.current.next());
    expect(result.current.index).toBe(1);
    // The second step carries no signal, so it never auto-completes.
    expect(result.current.step?.target).toBe("knowledge-attach");
    expect(result.current.signalMet).toBe(false);
    expect(result.current.isLast).toBe(true);

    act(() => result.current.next());
    expect(useOnboardingStore.getState().isOpen).toBe(false);
  });

  it("finish ends the flow, and an unread org list counts as none", () => {
    // `data` undefined (a list that errored rather than loaded) reads as zero, not
    // a crash — the `?? 0` guard the count leans on.
    rig.orgs = undefined;
    const { result } = renderHook(() => useOnboardingFlow());
    act(() => useOnboardingStore.getState().openFlow("create-org"));
    expect(result.current.signalMet).toBe(false);
    act(() => result.current.finish());
    expect(useOnboardingStore.getState().isOpen).toBe(false);
  });
});
