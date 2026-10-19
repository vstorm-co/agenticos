import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { STUCK_AFTER_MS, useAssistantSignals } from "./use-assistant-signals";
import { apiClient } from "@/lib/api-client";

const state = vi.hoisted(() => ({
  data: undefined as
    { pending_approvals: number; has_agents: boolean; failed_run_id: string | null } | undefined,
  orgId: "org-1" as string | null,
  options: null as { queryKey: unknown; enabled: boolean; queryFn: () => unknown } | null,
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: { queryKey: unknown; enabled: boolean; queryFn: () => unknown }) => {
    state.options = options;
    return { data: options.enabled ? state.data : undefined };
  },
}));
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
vi.mock("@/stores", () => ({
  useOrgStore: (pick: (s: { activeOrgId: string | null }) => unknown) =>
    pick({ activeOrgId: state.orgId }),
}));

beforeEach(() => {
  vi.useFakeTimers();
  state.data = { pending_approvals: 0, has_agents: true, failed_run_id: null };
  state.orgId = "org-1";
  state.options = null;
});

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

function wait(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

describe("useAssistantSignals", () => {
  it("reports what is waiting and an organization with nothing in it yet", () => {
    state.data = { pending_approvals: 3, has_agents: false, failed_run_id: null };
    const { result } = renderHook(() => useAssistantSignals());

    expect(result.current).toMatchObject({ pendingApprovals: 3, noAgents: true });
  });

  it("does not call an organization empty before the answer arrives", () => {
    state.data = undefined;
    const { result } = renderHook(() => useAssistantSignals());

    expect(result.current).toMatchObject({ pendingApprovals: 0, noAgents: false });
  });

  it("names the reader's own latest failed run of the last day", () => {
    state.data = { pending_approvals: 0, has_agents: true, failed_run_id: "run-2" };
    const { result } = renderHook(() => useAssistantSignals());

    expect(result.current.failedRunId).toBe("run-2");
  });

  it("asks once, under runs, and not before there is an organization", async () => {
    renderHook(() => useAssistantSignals());
    expect(state.options).toMatchObject({
      queryKey: ["runs", "assistant-signals", "org-1"],
      enabled: true,
    });
    await state.options?.queryFn();
    expect(apiClient.get).toHaveBeenCalledWith("/assistant/signals");

    state.orgId = null;
    renderHook(() => useAssistantSignals());
    expect(state.options).toMatchObject({ enabled: false });
  });

  it("notices a form left open for a minute, by its title", () => {
    document.body.innerHTML = `
      <div role="dialog" aria-labelledby="t"><h2 id="t"> Create a knowledge base </h2></div>`;
    const { result } = renderHook(() => useAssistantSignals());

    wait(30_000);
    expect(result.current.stuckIn).toBeNull();
    wait(STUCK_AFTER_MS);
    expect(result.current.stuckIn).toBe("Create a knowledge base");

    document.body.innerHTML = "";
    wait(5000);
    expect(result.current.stuckIn).toBeNull();
  });

  it("starts the minute again for a different form", () => {
    document.body.innerHTML = `<div role="dialog" aria-label="Invite people"></div>`;
    const { result } = renderHook(() => useAssistantSignals());
    wait(STUCK_AFTER_MS + 5000);
    expect(result.current.stuckIn).toBe("Invite people");

    document.title = "Agents";
    document.body.innerHTML = `<div role="dialog"></div>`;
    wait(5000);
    expect(result.current.stuckIn).toBeNull();
    wait(STUCK_AFTER_MS);
    expect(result.current.stuckIn).toBe("Agents");
  });

  it("never counts its own window as a form", () => {
    document.body.innerHTML = `<div role="dialog" data-assistant-window aria-label="AI Architect"></div>`;
    const { result } = renderHook(() => useAssistantSignals());

    wait(STUCK_AFTER_MS + 5000);

    expect(result.current.stuckIn).toBeNull();
  });
});
