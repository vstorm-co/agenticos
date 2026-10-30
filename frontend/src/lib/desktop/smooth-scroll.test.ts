import { beforeEach, describe, expect, it, vi } from "vitest";
import { smoothDesktopWheel } from "./smooth-scroll";

let scroller: HTMLElement;
let frames: Map<number, FrameRequestCallback>;
let next: number;
let clock: number;
function tick(count = 1): void {
  for (let index = 0; index < count; index++) {
    clock += 16;
    const pending = [...frames.values()];
    frames.clear();
    pending.forEach((callback) => callback(clock));
  }
}
function wheel(options: WheelEventInit = {}, target: EventTarget = scroller): WheelEvent {
  const event = new WheelEvent("wheel", {
    bubbles: true,
    cancelable: true,
    deltaY: 3,
    deltaMode: 1,
    ...options,
  });
  target.dispatchEvent(event);
  return event;
}
beforeEach(() => {
  frames = new Map();
  next = 0;
  clock = 0;
  vi.spyOn(performance, "now").mockImplementation(() => clock);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.set(++next, callback);
    return next;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  scroller = document.createElement("main");
  document.body.replaceChildren(scroller);
  Object.defineProperties(scroller, {
    scrollHeight: { value: 1500 },
    clientHeight: { value: 500 },
  });
  scroller.scrollTo = (options?: number | ScrollToOptions, y?: number): void => {
    scroller.scrollTop = typeof options === "number" ? (y ?? 0) : (options?.top ?? 0);
  };
});

describe("desktop wheel scrolling", () => {
  it("eases line notches and accumulates a burst without jumping", () => {
    const dispose = smoothDesktopWheel(scroller);
    expect(wheel().defaultPrevented).toBe(true);
    wheel();
    expect(scroller.scrollTop).toBe(0);
    tick();
    expect(scroller.scrollTop).toBeGreaterThan(0);
    expect(scroller.scrollTop).toBeLessThan(120);
    tick(100);
    expect(scroller.scrollTop).toBe(120);
    expect(frames.size).toBe(0);
    dispose();
  });
  it.each([0, 2])("handles discrete mode %i and clamps at both ends", (deltaMode) => {
    const dispose = smoothDesktopWheel(scroller);
    wheel({ deltaMode, deltaY: 1200 });
    tick(100);
    expect(scroller.scrollTop).toBe(1000);
    wheel({ deltaMode, deltaY: -1200 });
    tick(100);
    expect(scroller.scrollTop).toBe(0);
    dispose();
  });
  it.each([
    { deltaMode: 0, deltaY: 2.5 },
    { ctrlKey: true },
    { metaKey: true },
    { shiftKey: true },
    { deltaX: 1 },
    { deltaY: 0 },
  ])("keeps native input for %j", (options) => {
    const dispose = smoothDesktopWheel(scroller);
    expect(wheel(options).defaultPrevented).toBe(false);
    expect(frames.size).toBe(0);
    dispose();
  });
  it("leaves a nested scrolling panel in control of its own wheel input", () => {
    const nested = document.createElement("div");
    nested.style.overflowY = "auto";
    Object.defineProperties(nested, { scrollHeight: { value: 400 }, clientHeight: { value: 100 } });
    scroller.append(nested);
    const dispose = smoothDesktopWheel(scroller);
    expect(wheel({}, nested).defaultPrevented).toBe(false);
    expect(frames.size).toBe(0);
    dispose();
  });
  it.each(["text", "icon", "non-scrolling container"])(
    "scrolls the dashboard when the wheel starts on %s",
    (kind) => {
      const content =
        kind === "text"
          ? document.createTextNode("Card title")
          : kind === "icon"
            ? document.createElementNS("http://www.w3.org/2000/svg", "svg")
            : document.createElement("div");
      if (content instanceof HTMLElement) {
        content.style.overflowY = "hidden";
        Object.defineProperties(content, {
          scrollHeight: { value: 200 },
          clientHeight: { value: 100 },
        });
      }
      scroller.append(content);
      const dispose = smoothDesktopWheel(scroller);
      expect(wheel({}, content).defaultPrevented).toBe(true);
      tick(100);
      expect(scroller.scrollTop).toBe(60);
      dispose();
    },
  );

  it.each(["pointerdown", "touchstart", "keydown"])(
    "cancels animation on %s and removes listeners on disposal",
    (type) => {
      const dispose = smoothDesktopWheel(scroller);
      wheel();
      tick();
      const stopped = scroller.scrollTop;
      scroller.dispatchEvent(new Event(type));
      tick(100);
      expect(scroller.scrollTop).toBe(stopped);
      wheel();
      dispose();
      expect(frames.size).toBe(0);
      expect(wheel().defaultPrevented).toBe(false);
    },
  );
});
