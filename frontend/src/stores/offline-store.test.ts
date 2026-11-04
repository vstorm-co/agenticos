import { beforeEach, describe, expect, it } from "vitest";

import { useOfflineStore } from "./offline-store";

beforeEach(() => {
  useOfflineStore.getState().reset();
});

describe("useOfflineStore", () => {
  it("dates the screen by the oldest copy on it", () => {
    const older = new Date("2026-10-20T08:00:00Z");
    const newer = new Date("2026-10-22T08:00:00Z");
    useOfflineStore.getState().servedFromDevice(newer);
    useOfflineStore.getState().servedFromDevice(older);
    useOfflineStore.getState().servedFromDevice(newer);

    expect(useOfflineStore.getState().savedAt).toEqual(older);
  });

  it("forgets the copy once the server answers, and everything on reset", () => {
    useOfflineStore.getState().servedFromDevice(new Date());
    useOfflineStore.getState().setOutbox([{ conversationId: "c-1", count: 1 }]);
    useOfflineStore.getState().backOnline();
    expect(useOfflineStore.getState().savedAt).toBeNull();
    expect(useOfflineStore.getState().outbox).toHaveLength(1);

    useOfflineStore.getState().reset();
    expect(useOfflineStore.getState().outbox).toEqual([]);
  });
});
