import { afterEach, describe, expect, it, vi } from "vitest";
import { scrollGently } from "./scroll-gently";

const motion = vi.hoisted(() => ({ reduce: false }));
vi.mock("@/lib/motion", () => ({ prefersReducedMotion: () => motion.reduce }));
afterEach(() => {
  motion.reduce = false;
  vi.unstubAllGlobals();
});

describe("scrollGently", () => {
  function frames() {
    let next: FrameRequestCallback | undefined;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      next = callback;
      return 1;
    });
    const cancel = vi.fn(() => {
      next = undefined;
    });
    vi.stubGlobal("cancelAnimationFrame", cancel);
    return {
      tick: (time: number) => {
        const callback = next;
        next = undefined;
        callback?.(time);
      },
      cancel,
    };
  }
  it("glides to the new turn without an immediate jump or overshoot", () => {
    const clock = frames();
    const element = document.createElement("div");
    scrollGently(element, 400);
    expect(element.scrollTop).toBe(0);
    clock.tick(0);
    clock.tick(180);
    expect(element.scrollTop).toBe(350);
    clock.tick(360);
    expect(element.scrollTop).toBe(400);
    expect(clock.cancel).toHaveBeenCalled();
  });
  it.each(["wheel", "touchstart", "pointerdown", "keydown"])(
    "gives control back on %s",
    (event) => {
      const clock = frames();
      const element = document.createElement("div");
      scrollGently(element, 400);
      clock.tick(0);
      clock.tick(100);
      const before = element.scrollTop;
      element.dispatchEvent(new Event(event));
      clock.tick(360);
      expect(element.scrollTop).toBe(before);
      expect(clock.cancel).toHaveBeenCalled();
    },
  );
  it("cancels when the anchor is unmounted or another turn is sent", () => {
    const clock = frames();
    const element = document.createElement("div");
    const cancel = scrollGently(element, 400);
    cancel();
    clock.tick(360);
    expect(element.scrollTop).toBe(0);
  });
  it("honors reduced motion and clamps negative destinations", () => {
    motion.reduce = true;
    const element = document.createElement("div");
    scrollGently(element, 400)();
    expect(element.scrollTop).toBe(400);
    scrollGently(element, -50)();
    expect(element.scrollTop).toBe(0);
  });
});
