import { describe, expect, it } from "vitest";

import { applyBrowserFrame, browseById, isRunning, type Browse } from "./browse";
import type { BrowserFrame } from "@/types";

function frame(overrides: Partial<BrowserFrame> = {}): BrowserFrame {
  return { kind: "browser_step", call_id: "c1", step: 1, ...overrides };
}

function fold(...frames: BrowserFrame[]): Browse[] {
  return frames.reduce(applyBrowserFrame, [] as Browse[]);
}

describe("applyBrowserFrame - one browse per call_id", () => {
  it("opens a browse with its goal and its ceiling", () => {
    const [browse] = fold(
      frame({
        kind: "browser_opened",
        step: 0,
        goal: "find the price",
        max_steps: 25,
        url: "https://example.test/",
        title: "Example",
      }),
    );

    expect(browse).toMatchObject({
      callId: "c1",
      goal: "find the price",
      maxSteps: 25,
      url: "https://example.test/",
      steps: [],
      outcome: null,
    });
  });

  it("keeps two browses in one turn apart", () => {
    // A turn can browse twice. Keyed on the run, the second browse's steps would
    // be drawn into the first one's list.
    const browses = fold(
      frame({ kind: "browser_opened", call_id: "c1", step: 0, goal: "first" }),
      frame({ kind: "browser_opened", call_id: "c2", step: 0, goal: "second" }),
      frame({ call_id: "c2", step: 1, operation: "CLICK", target: "Accept" }),
    );

    expect(browses).toHaveLength(2);
    expect(browses[0]?.steps).toEqual([]);
    expect(browses[1]?.steps).toHaveLength(1);
  });

  it("records what was chosen and how sure the engine was", () => {
    const [browse] = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ step: 1, operation: "CLICK", target: "Accept all", confidence: 0.42 }),
    );

    expect(browse?.steps[0]).toMatchObject({
      step: 1,
      operation: "CLICK",
      target: "Accept all",
      confidence: 0.42,
    });
  });

  it("orders steps by their number rather than by arrival", () => {
    const [browse] = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ step: 2, operation: "SCROLL" }),
      frame({ step: 1, operation: "CLICK" }),
    );

    expect(browse?.steps.map((s) => s.step)).toEqual([1, 2]);
  });

  it("replaces a step it already holds rather than listing it twice", () => {
    const [browse] = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ step: 1, operation: "CLICK" }),
      frame({ step: 1, operation: "TYPE_TEXT" }),
    );

    expect(browse?.steps).toHaveLength(1);
    expect(browse?.steps[0]?.operation).toBe("TYPE_TEXT");
  });

  it("keeps only the newest viewport", () => {
    // One image, not a film strip: a browse sends one JPEG per step and the panel
    // shows the newest.
    const [browse] = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ kind: "browser_frame", step: 1, image: "data:image/jpeg;base64,AAA" }),
      frame({ kind: "browser_frame", step: 2, image: "data:image/jpeg;base64,BBB" }),
    );

    expect(browse?.image).toBe("data:image/jpeg;base64,BBB");
    expect(browse?.imageStep).toBe(2);
  });

  it("ignores a picture that arrived after the step which followed it", () => {
    // Frames share a socket with the turn's text. Drawing the older page under
    // the newer caption looks right, which is why it is worse than drawing nothing.
    const [browse] = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ kind: "browser_frame", step: 3, image: "data:image/jpeg;base64,NEW" }),
      frame({ kind: "browser_frame", step: 2, image: "data:image/jpeg;base64,OLD" }),
    );

    expect(browse?.image).toBe("data:image/jpeg;base64,NEW");
    expect(browse?.imageStep).toBe(3);
  });

  it("keeps what it already knows when a frame omits it", () => {
    // Only the opening frame carries the goal and the ceiling, and a step frame
    // on a page that has not navigated carries no new URL. Every later frame
    // falling back to what is held is what stops the panel blanking its header
    // between steps.
    const [browse] = fold(
      frame({
        kind: "browser_opened",
        step: 0,
        url: "https://example.test/",
        title: "Example",
      }),
      frame({ kind: "browser_frame", step: 1, image: "data:image/jpeg;base64,AAA" }),
      frame({ step: 1, operation: "SCROLL" }),
      frame({ kind: "browser_finished", step: 2, outcome: "done" }),
    );

    expect(browse).toMatchObject({
      url: "https://example.test/",
      title: "Example",
      image: "data:image/jpeg;base64,AAA",
      outcome: "done",
    });
  });

  it("keeps the picture it has when a frame arrives without one", () => {
    const [browse] = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ kind: "browser_frame", step: 1, image: "data:image/jpeg;base64,AAA" }),
      frame({ kind: "browser_frame", step: 2 }),
    );

    expect(browse?.image).toBe("data:image/jpeg;base64,AAA");
  });

  it("records the outcome and what it says about the page", () => {
    const [browse] = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ kind: "browser_finished", step: 4, outcome: "blocked", detail: "Please sign in" }),
    );

    expect(browse?.outcome).toBe("blocked");
    expect(browse?.detail).toBe("Please sign in");
    expect(isRunning(browse as Browse)).toBe(false);
  });

  it("keeps the frames of a browse whose opening frame it never saw", () => {
    // A socket that reconnected mid-browse delivers the rest, and showing those
    // beats discarding them because the first one was missed.
    const [browse] = fold(frame({ step: 7, operation: "CLICK", target: "Next" }));

    expect(browse?.callId).toBe("c1");
    expect(browse?.steps).toHaveLength(1);
  });

  it("keeps the steps when a second opening frame arrives", () => {
    const [browse] = fold(
      frame({ step: 1, operation: "CLICK" }),
      frame({ kind: "browser_opened", step: 0, goal: "late" }),
    );

    expect(browse?.goal).toBe("late");
    expect(browse?.steps).toHaveLength(1);
  });
});

describe("browseById - which browse a panel was opened on", () => {
  it("finds the one whose id was asked for", () => {
    const browses = fold(
      frame({ kind: "browser_opened", call_id: "c1", step: 0, goal: "first" }),
      frame({ kind: "browser_opened", call_id: "c2", step: 0, goal: "second" }),
    );

    expect(browseById(browses, "c2")?.goal).toBe("second");
  });

  it("answers nothing for an id the turn no longer holds", () => {
    // The turn that owned it ended and its browses were dropped, while the
    // panel was still open on one of them.
    expect(browseById([], "c1")).toBeNull();
  });

  it("answers nothing when no browse is open", () => {
    const browses = fold(frame({ kind: "browser_opened", call_id: "c1", step: 0 }));
    expect(browseById(browses, null)).toBeNull();
  });
});
