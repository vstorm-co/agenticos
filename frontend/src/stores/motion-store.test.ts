import { beforeEach, describe, expect, it } from "vitest";

import { MOTION_STORAGE_KEY } from "@/lib/motion-preference";

import { useMotionStore } from "./motion-store";

beforeEach(() => {
  useMotionStore.setState({ motion: "system" });
});

describe("useMotionStore", () => {
  it("follows the operating system until told otherwise", () => {
    expect(useMotionStore.getState().motion).toBe("system");
  });

  it("keeps the choice in this browser, under the key the no-flash script reads", () => {
    useMotionStore.getState().setMotion("reduce");

    expect(useMotionStore.getState().motion).toBe("reduce");
    expect(JSON.parse(localStorage.getItem(MOTION_STORAGE_KEY) ?? "{}")).toMatchObject({
      state: { motion: "reduce" },
    });
  });
});
