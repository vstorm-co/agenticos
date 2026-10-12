import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createTourSpotlight, travelMs, type TourSpotlight } from "./tour-spotlight";

/**
 * The layer is driven by `requestAnimationFrame`, so the tests run the frames by
 * hand: `frame(ms)` advances the clock and runs whatever was queued, the way a
 * browser paints one frame. jsdom lays nothing out, so each control's box is
 * whatever the test says it is.
 */
let queued: FrameRequestCallback[] = [];
let clock = 0;

function frame(advance = 16) {
  clock += advance;
  const run = queued;
  queued = [];
  for (const callback of run) callback(clock);
}

function control(box: { x: number; y: number; width: number; height: number }): HTMLElement {
  const element = document.createElement("button");
  document.body.appendChild(element);
  element.getBoundingClientRect = () =>
    ({
      ...box,
      left: box.x,
      top: box.y,
      right: box.x + box.width,
      bottom: box.y + box.height,
    }) as DOMRect;
  return element;
}

function ring(): HTMLElement {
  return document.querySelector<HTMLElement>(".tour-spotlight-ring")!;
}

function hole(): string {
  return document.querySelector(".tour-spotlight-dim path")!.getAttribute("d")!;
}

let light: TourSpotlight;

beforeEach(() => {
  queued = [];
  clock = 0;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    queued.push(callback);
    return queued.length;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {
    queued = [];
  });
  vi.spyOn(performance, "now").mockImplementation(() => clock);
});

afterEach(() => {
  light?.destroy();
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("createTourSpotlight", () => {
  it("frames the control with a ring and cuts the dim around it", async () => {
    light = createTourSpotlight(false);
    await light.focus(control({ x: 100, y: 200, width: 80, height: 30 }));
    frame();

    // Stood off by the 8px padding on every side.
    expect(ring().style.left).toBe("92px");
    expect(ring().style.top).toBe("192px");
    expect(ring().style.width).toBe("96px");
    expect(ring().style.height).toBe("46px");
    expect(ring().classList.contains("is-visible")).toBe(true);
    // The cut-out opens at the same box, its top-left plus the 10px corner.
    expect(hole()).toContain("M102,192");
  });

  it("dims the whole page and hides the ring when there is nothing to light", async () => {
    // The welcome and the farewell describe no control. driver.js shrank its light
    // to a dot in the middle of the screen for them, which read as a glitch.
    light = createTourSpotlight(false);
    await light.focus(control({ x: 100, y: 200, width: 80, height: 30 }));
    frame();
    await light.focus(null);
    frame();

    expect(ring().classList.contains("is-visible")).toBe(false);
    expect(hole()).not.toContain("z");
    expect(hole()).toBe(
      `M${window.innerWidth},0 L0,0 L0,${window.innerHeight} L${window.innerWidth},${window.innerHeight} Z`,
    );
  });

  it("travels from one control to the next, and resolves when it lands", async () => {
    light = createTourSpotlight(false);
    await light.focus(control({ x: 0, y: 0, width: 100, height: 40 }));
    frame();

    let landed = false;
    const arriving = light.focus(control({ x: 600, y: 0, width: 100, height: 40 }));
    void arriving.then(() => (landed = true));
    const duration = travelMs(600);

    frame(duration / 2);
    await Promise.resolve();
    // Halfway in time is halfway in space under an ease-in-out, and not yet landed.
    expect(Number.parseFloat(ring().style.left)).toBeCloseTo(-8 + 300, 0);
    expect(landed).toBe(false);

    frame(duration / 2);
    await arriving;
    expect(ring().style.left).toBe("592px");
    expect(landed).toBe(true);
  });

  it("lands on where the control is when it arrives, not where it was when it left", async () => {
    // A tab's panel settling, a list loading in: the target moves mid-travel.
    light = createTourSpotlight(false);
    await light.focus(control({ x: 0, y: 0, width: 100, height: 40 }));
    frame();
    const box = { x: 400, y: 0, width: 100, height: 40 };
    const target = control(box);
    const arriving = light.focus(target);

    box.y = 300;
    frame(1000);
    await arriving;
    expect(ring().style.top).toBe("292px");
  });

  it("keeps following the control after it has landed", async () => {
    light = createTourSpotlight(false);
    const box = { x: 100, y: 100, width: 100, height: 40 };
    await light.focus(control(box));
    frame();

    box.y = 250;
    frame();
    expect(ring().style.top).toBe("242px");
  });

  it("holds the light where it was when the control leaves the document", async () => {
    // Its page navigated away. A detached element measures 0×0 at the origin,
    // which would drag the light to the corner of the screen.
    light = createTourSpotlight(false);
    const target = control({ x: 300, y: 300, width: 100, height: 40 });
    await light.focus(target);
    frame();
    target.remove();
    frame();

    expect(ring().style.left).toBe("292px");
    expect(ring().classList.contains("is-visible")).toBe(true);
  });

  it("arrives at once, without travel, from a page with nothing lit", async () => {
    // There is no "from" to glide out of, so it appears on the control rather
    // than sliding in from wherever the last one was.
    light = createTourSpotlight(false);
    await light.focus(null);
    frame();
    await light.focus(control({ x: 500, y: 500, width: 100, height: 40 }));
    frame();

    expect(ring().style.left).toBe("492px");
  });

  it("snaps instead of travelling for a reader who asked for reduced motion", async () => {
    light = createTourSpotlight(true);
    await light.focus(control({ x: 0, y: 0, width: 100, height: 40 }));
    frame();
    await light.focus(control({ x: 600, y: 0, width: 100, height: 40 }));
    frame();

    expect(ring().style.left).toBe("592px");
  });

  it("resolves a travel that a later step overtook, so nothing waits on it forever", async () => {
    light = createTourSpotlight(false);
    await light.focus(control({ x: 0, y: 0, width: 100, height: 40 }));
    frame();

    const overtaken = light.focus(control({ x: 600, y: 0, width: 100, height: 40 }));
    void light.focus(control({ x: 0, y: 600, width: 100, height: 40 }));
    await expect(overtaken).resolves.toBeUndefined();
  });

  it("resolves at once when asked to light the control it already lights", async () => {
    light = createTourSpotlight(false);
    const target = control({ x: 0, y: 0, width: 100, height: 40 });
    await light.focus(target);
    frame();

    await expect(light.focus(target)).resolves.toBeUndefined();
  });

  it("redraws nothing on a frame where nothing moved", async () => {
    light = createTourSpotlight(false);
    await light.focus(control({ x: 100, y: 100, width: 100, height: 40 }));
    frame();
    const path = document.querySelector(".tour-spotlight-dim path")!;
    const write = vi.spyOn(path, "setAttribute");
    frame();

    expect(write).not.toHaveBeenCalled();
  });

  it("takes its layer down and stops painting when destroyed", async () => {
    light = createTourSpotlight(false);
    const pending = light.focus(null);
    frame();
    light.destroy();

    await expect(pending).resolves.toBeUndefined();
    expect(document.querySelector(".tour-spotlight")).toBeNull();
    expect(queued).toHaveLength(0);
  });
});

describe("travelMs", () => {
  it("keeps a short hop visible and a long sweep from dragging", () => {
    expect(travelMs(0)).toBe(280);
    expect(travelMs(400)).toBe(380);
    expect(travelMs(5000)).toBe(700);
  });
});
