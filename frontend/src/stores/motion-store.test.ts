import { beforeEach, describe, expect, it } from "vitest";

import { DEFAULT_MOTION_PREFERENCE, MOTION_STORAGE_KEY } from "@/lib/motion-preference";

import { useMotionStore } from "./motion-store";

beforeEach(() => {
  useMotionStore.setState(useMotionStore.getInitialState());
  localStorage.removeItem(MOTION_STORAGE_KEY);
});

describe("useMotionStore", () => {
  it("starts with Full when this browser has no stored preference", async () => {
    await useMotionStore.persist.rehydrate();
    expect(useMotionStore.getInitialState().motion).toBe(DEFAULT_MOTION_PREFERENCE);
    expect(useMotionStore.getState().motion).toBe("full");
  });

  it.each(["system", "reduce"] as const)(
    "preserves the explicit stored %s choice",
    async (motion) => {
      const stored = JSON.stringify({ state: { motion }, version: 0 });
      localStorage.setItem(MOTION_STORAGE_KEY, stored);

      await useMotionStore.persist.rehydrate();

      expect(useMotionStore.getState().motion).toBe(motion);
      expect(localStorage.getItem(MOTION_STORAGE_KEY)).toBe(stored);
    },
  );

  it.each(["{not json", JSON.stringify({ state: { motion: "unknown" }, version: 0 })])(
    "keeps Full when stored data is unreadable or unknown: %s",
    async (stored) => {
      localStorage.setItem(MOTION_STORAGE_KEY, stored);

      await useMotionStore.persist.rehydrate();

      expect(useMotionStore.getState().motion).toBe("full");
      expect(localStorage.getItem(MOTION_STORAGE_KEY)).toBe(stored);
    },
  );

  it("retains the default setter after restoring a stored choice", async () => {
    localStorage.setItem(MOTION_STORAGE_KEY, JSON.stringify({ state: { motion: "system" } }));
    await useMotionStore.persist.rehydrate();
    useMotionStore.getState().setMotion("reduce");
    expect(useMotionStore.getState().motion).toBe("reduce");
  });

  it("keeps the choice in this browser, under the key the no-flash script reads", () => {
    useMotionStore.getState().setMotion("reduce");

    expect(useMotionStore.getState().motion).toBe("reduce");
    expect(JSON.parse(localStorage.getItem(MOTION_STORAGE_KEY) ?? "{}")).toMatchObject({
      state: { motion: "reduce" },
    });
  });
});
