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
});
