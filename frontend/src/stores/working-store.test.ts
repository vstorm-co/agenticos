import { beforeEach, describe, expect, it } from "vitest";

import { useWorkingStore } from "./working-store";

beforeEach(() => useWorkingStore.getState().reset());

describe("useWorkingStore", () => {
  it("keeps one start per conversation, and forgets it when the turn stops", () => {
    const { start, stop } = useWorkingStore.getState();
    start("c-1", "2026-10-16T09:00:00Z");
    start("c-2", "2026-10-16T09:01:00Z");
    stop("c-1");

    expect(useWorkingStore.getState().since).toEqual({ "c-2": "2026-10-16T09:01:00Z" });
  });

  it("leaves the state alone when a conversation it never started stops", () => {
    const before = useWorkingStore.getState().since;
    useWorkingStore.getState().stop("c-9");

    expect(useWorkingStore.getState().since).toBe(before);
  });

  it("forgets every conversation on reset", () => {
    useWorkingStore.getState().start("c-1", "2026-10-16T09:00:00Z");
    useWorkingStore.getState().reset();

    expect(useWorkingStore.getState().since).toEqual({});
  });

  it("keeps a handed-off thread's mark when its tab's turn stops, until it settles", () => {
    // Opening another thread lets the turn go to the server; the row must not go
    // idle before the listing has seen the run.
    const { start, stop, handOff, settle } = useWorkingStore.getState();
    start("c-1", "2026-10-16T09:00:00Z");
    handOff("c-1");
    stop("c-1");
    expect(useWorkingStore.getState().since).toEqual({ "c-1": "2026-10-16T09:00:00Z" });

    settle("c-1");
    expect(useWorkingStore.getState()).toMatchObject({ since: {}, handedOff: {} });
  });

  it("hands off only a thread it is working in, and settles nothing it does not hold", () => {
    const before = useWorkingStore.getState();
    before.handOff("c-9");
    before.settle("c-9");

    expect(useWorkingStore.getState()).toBe(before);
  });
});
