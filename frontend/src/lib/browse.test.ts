import { describe, expect, it } from "vitest";

import {
  recordedBrowserPage,
  turnBrowseVisits,
  applyBrowserFrame,
  browseById,
  isRunning,
  withLivePreview,
  type Browse,
} from "./browse";
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
      frame({ step: 1, operation: "CLICK", target: "Accept all", reason: "Close the banner" }),
    );

    expect(browse?.steps[0]).toMatchObject({
      step: 1,
      operation: "CLICK",
      target: "Accept all",
      reason: "Close the banner",
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

  it("drops a late frame for a browse this turn never opened", () => {
    // A background delegation from the previous turn emits a step after the
    // turn boundary cleared `browses`. Reconstructing it would put that browse -
    // and its screenshot of another page - under the new transcript.
    expect(fold(frame({ step: 7, operation: "CLICK", target: "Next" }))).toEqual([]);
    expect(
      fold(frame({ kind: "browser_frame", step: 7, image: "data:image/jpeg;base64,X" })),
    ).toEqual([]);
    expect(fold(frame({ kind: "browser_finished", step: 7, outcome: "done" }))).toEqual([]);
  });

  it("keeps the steps when a second opening frame arrives", () => {
    const [browse] = fold(
      frame({ kind: "browser_opened", step: 0, goal: "first" }),
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

describe("applyBrowserFrame - a person and the browser (#2128)", () => {
  it("knows the run it belongs to, which addresses its live view", () => {
    const [browse] = fold(frame({ kind: "browser_opened", step: 0, run_id: "run-7" }));
    expect(browse?.runId).toBe("run-7");
  });

  it("says what it needs until somebody takes it over, then who has it", () => {
    const asked = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ kind: "browser_needs_person", step: 2, detail: "Sign in" }),
    );
    expect(asked[0]).toMatchObject({ needs: "Sign in", heldBy: null });

    const held = applyBrowserFrame(
      asked,
      frame({ kind: "browser_held", step: 2, by: "Ada", by_user_id: "u1" }),
    );
    expect(held[0]).toMatchObject({ needs: null, heldBy: "Ada", heldById: "u1" });

    const back = applyBrowserFrame(held, frame({ kind: "browser_released", step: 2 }));
    expect(back[0]).toMatchObject({ heldBy: null, heldById: null });
  });

  it("reads a frame with nothing in it as nothing needed and nobody named", () => {
    const [browse] = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ kind: "browser_needs_person", step: 1 }),
      frame({ kind: "browser_held", step: 1 }),
    );
    expect(browse).toMatchObject({ runId: null, needs: null, heldBy: null });
  });

  it("forgets both once the browse has ended", () => {
    const [browse] = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ kind: "browser_needs_person", step: 1, detail: "Sign in" }),
      frame({ kind: "browser_finished", step: 1, outcome: "blocked" }),
    );
    expect(browse).toMatchObject({ needs: null, heldBy: null, outcome: "blocked" });
  });
});

describe("applyBrowserFrame - the agent's cursor", () => {
  it("points where the agent is about to press, and hides while a person holds it or once it ends", () => {
    const pointed = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ kind: "browser_pointer", step: 2, x: 0.25, y: 0.5 }),
    );
    expect(pointed[0]?.pointer).toEqual({ x: 0.25, y: 0.5, step: 2 });

    const held = applyBrowserFrame(pointed, frame({ kind: "browser_held", step: 2, by: "Ada" }));
    expect(held[0]?.pointer).toBeNull();

    const ended = applyBrowserFrame(
      pointed,
      frame({ kind: "browser_finished", step: 3, outcome: "done" }),
    );
    expect(ended[0]?.pointer).toBeNull();
  });

  it("reads a pointer frame with no position as the corner", () => {
    const [browse] = fold(
      frame({ kind: "browser_opened", step: 0 }),
      frame({ kind: "browser_pointer", step: 1 }),
    );
    expect(browse?.pointer).toEqual({ x: 0, y: 0, step: 1 });
  });
});

it("keeps navigation capability and control errors separate from painted frames", () => {
  const opened = applyBrowserFrame([], {
    kind: "browser_opened",
    call_id: "tab",
    step: 0,
    navigable: true,
  });
  expect(opened[0]?.navigable).toBe(true);
  const refused = applyBrowserFrame(opened, {
    kind: "browser_control_error",
    call_id: "tab",
    step: 0,
    detail: "Outside allowed domains",
  });
  expect(refused[0]?.controlError).toBe("Outside allowed domains");
  const cleared = applyBrowserFrame(refused, {
    kind: "browser_control_error",
    call_id: "tab",
    step: 0,
  });
  expect(cleared[0]?.controlError).toBeNull();
});

it("keeps completion authoritative while retaining the cached final picture", () => {
  const streamed = fold(
    frame({ kind: "browser_opened" }),
    frame({ kind: "browser_finished", outcome: "done" }),
  )[0]!;
  const live = { ...streamed, image: "cached-final", imageStep: 3, outcome: null };
  expect(withLivePreview(streamed, live)).toMatchObject({
    outcome: "done",
    image: "cached-final",
    imageStep: 3,
  });
  expect(withLivePreview(streamed, null)).toBe(streamed);
  expect(withLivePreview(streamed, { ...live, callId: "other" })).toBe(streamed);
  expect(withLivePreview({ ...streamed, outcome: null }, live)).toBe(live);
  expect(
    withLivePreview({ ...streamed, image: "streamed", imageStep: 4 }, { ...live, image: null }),
  ).toMatchObject({ image: "streamed", imageStep: 4 });
});

it("accepts a delayed first image after newer metadata without treating metadata as a picture", () => {
  const [browse] = fold(
    frame({ kind: "browser_opened", step: 0 }),
    frame({ kind: "browser_frame", step: 5, url: "https://example.test/next" }),
    frame({ kind: "browser_frame", step: 3, image: "delayed-first-picture" }),
  );
  expect(browse).toMatchObject({ image: "delayed-first-picture", imageStep: 3 });
});

describe("recordedBrowserPage", () => {
  it.each([
    [
      { args: {}, result: "PAGE: A - title - https://example.com/article\n" },
      { url: "https://example.com/article", title: "A - title" },
    ],
    [
      { args: { url: "https://old.example" }, result: "PAGE: New page - https://example.com/new" },
      { url: "https://example.com/new", title: "New page" },
    ],
    [{ args: { start_url: "http://example.com" } }, { url: "http://example.com/", title: null }],
    [
      { args: { url: "https://example.com" }, result: { text: "not a report" } },
      { url: "https://example.com/", title: null },
    ],
    [
      { args: {}, result: "PAGE: (untitled) - https://example.com" },
      { url: "https://example.com/", title: null },
    ],
    [
      { args: {}, result: "PAGE: Invalid - https://[broken" },
      { url: null, title: null },
    ],
    [{ args: { url: "javascript:alert(1)" } }, { url: null, title: null }],
    [{ args: { url: "file:///etc/passwd" } }, { url: null, title: null }],
    [{ args: { url: 123 } }, { url: null, title: null }],
    [{ args: {} }, { url: null, title: null }],
  ])("extracts a safe page identity from %j", (call, expected) => {
    expect(recordedBrowserPage(call)).toEqual(expected);
  });
});

describe("turnBrowseVisits", () => {
  const call = (id: string, name: string, args: Record<string, unknown> = {}, result?: string) => ({
    id,
    name,
    args,
    result,
    status: "completed" as const,
  });
  const report = (title: string) => `PAGE: ${title} - https://example.com/page`;

  it("keeps separate tabs even at the same URL and updates the original tab after switching back", () => {
    const calls = [
      call("first", "browser_open", {}, report("First")),
      call("second", "browser_new_tab", {}, `TAB: two\n${report("Second")}`),
      call("switch", "browser_switch_tab", { tab_id: "main" }, report("First updated")),
    ];
    const entries = turnBrowseVisits(calls, []);
    expect(entries.map((entry) => entry.id)).toEqual(["first", "second"]);
    expect(entries.map((entry) => entry.call.id)).toEqual(["switch", "second"]);
  });

  it("uses the selected tab after listing or closing tabs and ignores failed switches and non-browser tools", () => {
    const calls = [
      call("first", "browser_open", {}, report("First")),
      call(
        "second",
        "browser_new_tab",
        { url: "https://example.com/page" },
        `TAB: two\n${report("Second")}`,
      ),
      call("list", "browser_tabs", {}, "* main: First - https://example.com/page"),
      call("failed", "browser_switch_tab", { tab_id: "missing" }, "That tab is not open"),
      call("mcp", "mcp_browser_read", {}, report("Unrelated")),
      call(
        "close",
        "browser_close_tab",
        {},
        "Closed tab.\n* main: First - https://example.com/page",
      ),
      call("read", "browser_read", {}, report("Updated")),
      call("pending", "browser_click"),
      call("empty-list", "browser_tabs"),
    ];
    const entries = turnBrowseVisits(calls, []);
    expect(entries).toHaveLength(2);
    expect(entries[0]?.call.id).toBe("read");
    expect(entries[1]?.id).toBe("second");
  });

  it("accepts a read from a switch without an explicit id without duplicating the selected tab", () => {
    expect(
      turnBrowseVisits(
        [
          call("open", "browser_open", {}, report("First")),
          call("switch", "browser_switch_tab", {}, report("Updated")),
        ],
        [],
      ),
    ).toHaveLength(1);
  });

  it("ignores list and close replies without a selected tab", () => {
    expect(
      turnBrowseVisits(
        [call("list", "browser_tabs", {}, "No tabs"), call("close", "browser_close_tab")],
        [],
      ),
    ).toEqual([]);
  });
});

it("does not invent a card when a new tab is refused or has not opened yet", () => {
  const calls = [
    {
      id: "pending",
      name: "browser_new_tab",
      args: { url: "https://example.com" },
      status: "running" as const,
    },
    {
      id: "limit",
      name: "browser_new_tab",
      args: { url: "https://example.com" },
      result: "Eight tabs are open.",
      status: "completed" as const,
    },
    {
      id: "refused",
      name: "browser_new_tab",
      args: { url: "https://example.com" },
      result: "TAB: refused\nOutside allowed domains",
      status: "completed" as const,
    },
  ];
  expect(turnBrowseVisits(calls, [])).toEqual([]);
});
