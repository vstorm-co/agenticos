import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/*
 * The page side of a bound artifact's data runs in the served page, not in the
 * console, so it lives beside the backend that writes it into that page. Read
 * from there and run here, in jsdom, against a stub window whose timers are
 * vitest's fake ones.
 */
const source = readFileSync(
  join(process.cwd(), "..", "backend", "app", "core", "catalog", "artifact_data_bridge.js"),
  "utf8",
);

interface BridgeConfig {
  n: string;
  live: boolean;
  names: string[];
  initial?: unknown;
  actions?: boolean;
}

type Bindings = Record<string, unknown>;

interface Agenticos {
  data: Promise<Bindings>;
  onData: (fn: (bindings: Bindings) => void) => void;
  run: (action: unknown, input?: unknown) => Promise<unknown>;
  onRun: (fn: (event: unknown) => void) => () => void;
}

interface Parent {
  postMessage: ReturnType<typeof vi.fn>;
}

interface StubWindow {
  parent: Parent | StubWindow;
  agenticos?: Agenticos;
  addEventListener: (type: string, listener: (event: MessageEvent) => void) => void;
  setTimeout: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>;
  clearTimeout: (id: ReturnType<typeof setTimeout>) => void;
}

type Bridge = (window: StubWindow, document: Document, config: BridgeConfig) => void;

const UNAVAILABLE = {
  status: "unavailable",
  records: [],
  fields: {},
  truncated: false,
  limit: null,
  count: 0,
};

const OK = {
  status: "ok",
  records: [{ id: "r1", stage: "</script><img src=x onerror=alert(1)>" }],
  fields: {},
  truncated: false,
  limit: null,
  count: 1,
};

function start(
  config: Partial<BridgeConfig> = {},
  options: { orphan?: boolean; readyState?: DocumentReadyState } = {},
) {
  const bridge = (0, eval)(`(${source})`) as Bridge;
  const parent: Parent = { postMessage: vi.fn() };
  const listeners: ((event: MessageEvent) => void)[] = [];
  const loads: (() => void)[] = [];
  const stub: StubWindow = {
    parent,
    addEventListener: (type, listener) => {
      if (type === "message") listeners.push(listener);
      if (type === "load") loads.push(() => listener(new Event("load") as MessageEvent));
    },
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
  };
  if (options.orphan) stub.parent = stub;
  // A page whose platform script runs while it is still parsing, unless told otherwise.
  const page = { readyState: options.readyState ?? "loading" } as Document;
  bridge(stub, page, { n: "nonce-1", live: true, names: ["deals", "owners"], ...config });
  const load = () => {
    for (const listener of loads) listener();
  };
  const dispatch = (data: unknown, source: unknown = parent) => {
    for (const listener of listeners) listener({ data, source } as MessageEvent);
  };
  return { agenticos: stub.agenticos as Agenticos, parent, dispatch, listeners, load, loads };
}

function ready(subscribes: boolean) {
  return [{ type: "agenticos:ready", n: "nonce-1", subscribes }, "*"];
}

describe("the artifact data bridge", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("resolves every binding unavailable at once when not live", async () => {
    const { agenticos, parent, listeners } = start({ live: false });
    await expect(agenticos.data).resolves.toEqual({ deals: UNAVAILABLE, owners: UNAVAILABLE });
    vi.advanceTimersByTime(20_000);
    expect(parent.postMessage).not.toHaveBeenCalled();
    expect(listeners).toHaveLength(0);
  });

  it("resolves every binding unavailable at once with no parent", async () => {
    const { agenticos, parent } = start({}, { orphan: true });
    await expect(agenticos.data).resolves.toEqual({ deals: UNAVAILABLE, owners: UNAVAILABLE });
    vi.advanceTimersByTime(20_000);
    expect(parent.postMessage).not.toHaveBeenCalled();
  });

  it("resends ready with backoff until data arrives", () => {
    const { parent, dispatch } = start();
    const posts = () => parent.postMessage.mock.calls.length;
    expect(parent.postMessage).toHaveBeenLastCalledWith(...ready(false));
    // Posted at 0, 100, 300, 700, 1500 and 3100 ms: the gap doubles from 100 ms.
    const expected: [number, number][] = [
      [99, 1],
      [1, 2],
      [199, 2],
      [1, 3],
      [400, 4],
      [800, 5],
      [1600, 6],
    ];
    for (const [ms, count] of expected) {
      vi.advanceTimersByTime(ms);
      expect(posts()).toBe(count);
    }
    // Then capped at 2 s: 5100 ms, not 6300.
    vi.advanceTimersByTime(1999);
    expect(posts()).toBe(6);
    vi.advanceTimersByTime(1);
    expect(posts()).toBe(7);
    dispatch({ type: "agenticos:data", n: "nonce-1", bindings: { deals: OK, owners: OK } });
    vi.advanceTimersByTime(20_000);
    expect(posts()).toBe(7);
  });

  it("gives up after 10 s and resolves every binding unavailable", async () => {
    const { agenticos, parent } = start();
    const seen = vi.fn();
    agenticos.onData(seen);
    let settled = false;
    void agenticos.data.then(() => {
      settled = true;
    });
    vi.advanceTimersByTime(9_999);
    await Promise.resolve();
    expect(settled).toBe(false);
    vi.advanceTimersByTime(1);
    await expect(agenticos.data).resolves.toEqual({ deals: UNAVAILABLE, owners: UNAVAILABLE });
    expect(seen).toHaveBeenCalledWith({ deals: UNAVAILABLE, owners: UNAVAILABLE });
    const asked = parent.postMessage.mock.calls.length;
    vi.advanceTimersByTime(20_000);
    expect(parent.postMessage.mock.calls.length).toBe(asked);
  });

  it("ignores data from any window but its parent", async () => {
    const { agenticos, dispatch } = start();
    const seen = vi.fn();
    agenticos.onData(seen);
    dispatch({ type: "agenticos:data", n: "nonce-1", bindings: { deals: OK } }, {});
    dispatch({ type: "agenticos:data", n: "nonce-1", bindings: { deals: OK } }, null);
    expect(seen).not.toHaveBeenCalled();
    vi.advanceTimersByTime(10_000);
    await expect(agenticos.data).resolves.toEqual({ deals: UNAVAILABLE, owners: UNAVAILABLE });
  });

  it("ignores data with another nonce", async () => {
    const { agenticos, dispatch } = start();
    const seen = vi.fn();
    agenticos.onData(seen);
    dispatch({ type: "agenticos:data", n: "nonce-0", bindings: { deals: OK } });
    dispatch({ type: "agenticos:data", bindings: { deals: OK } });
    dispatch({ type: "agenticos:open-link", n: "nonce-1", href: "https://example.com" });
    dispatch("agenticos:data");
    dispatch(null);
    expect(seen).not.toHaveBeenCalled();
    vi.advanceTimersByTime(10_000);
    await expect(agenticos.data).resolves.toEqual({ deals: UNAVAILABLE, owners: UNAVAILABLE });
  });

  it("fills a declared name missing from the post as unavailable and drops undeclared ones", async () => {
    const { agenticos, dispatch } = start({ names: ["deals", "owners", "__proto__"] });
    dispatch({
      type: "agenticos:data",
      n: "nonce-1",
      bindings: { deals: OK, extra: OK, owners: "not an object" },
    });
    const data = await agenticos.data;
    expect(Object.keys(data)).toEqual(["deals", "owners", "__proto__"]);
    expect(data.deals).toEqual(OK);
    expect(data.owners).toEqual(UNAVAILABLE);
    // An own key named `__proto__`, never the answer's prototype.
    expect(Object.getPrototypeOf(data)).toBe(Object.prototype);
    expect(Object.getOwnPropertyDescriptor(data, "__proto__")?.value).toEqual(UNAVAILABLE);
    expect("extra" in data).toBe(false);
  });

  it("calls every onData listener on each post and resolves data once", async () => {
    const { agenticos, dispatch } = start();
    const first = vi.fn();
    const second = vi.fn();
    agenticos.onData(first);
    agenticos.onData(second);
    dispatch({ type: "agenticos:data", n: "nonce-1", bindings: { deals: OK } });
    dispatch({ type: "agenticos:data", n: "nonce-1", bindings: { owners: OK } });
    expect(first).toHaveBeenCalledTimes(2);
    expect(second).toHaveBeenCalledTimes(2);
    expect(second).toHaveBeenLastCalledWith({ deals: UNAVAILABLE, owners: OK });
    await expect(agenticos.data).resolves.toEqual({ deals: OK, owners: UNAVAILABLE });
  });

  it("calls a late onData listener at once and says it subscribes", () => {
    const { agenticos, parent, dispatch } = start();
    dispatch({ type: "agenticos:data", n: "nonce-1", bindings: { deals: OK, owners: OK } });
    const asked = parent.postMessage.mock.calls.length;
    const late = vi.fn();
    agenticos.onData(late);
    expect(late).toHaveBeenCalledWith({ deals: OK, owners: OK });
    expect(parent.postMessage.mock.calls.length).toBe(asked + 1);
    expect(parent.postMessage).toHaveBeenLastCalledWith(...ready(true));
    // Once: a second listener changes nothing the console needs to know.
    agenticos.onData(vi.fn());
    expect(parent.postMessage.mock.calls.length).toBe(asked + 1);
  });

  it("says ready once more when the page has loaded, without asking again", () => {
    // The console forgets the handshake when the frame loads, which comes after
    // this page asked and was answered: one more ready tells it this page listens.
    const { agenticos, parent, dispatch, load } = start();
    agenticos.onData(vi.fn());
    dispatch({ type: "agenticos:data", n: "nonce-1", bindings: { deals: OK, owners: OK } });
    const asked = parent.postMessage.mock.calls.length;

    load();
    expect(parent.postMessage.mock.calls.length).toBe(asked + 1);
    expect(parent.postMessage).toHaveBeenLastCalledWith(...ready(true));

    load();
    vi.advanceTimersByTime(20_000);
    expect(parent.postMessage.mock.calls.length).toBe(asked + 1);
  });

  it("adds no ready for a page that had loaded before the bridge ran", () => {
    const { parent, dispatch, load, loads } = start({}, { readyState: "complete" });
    dispatch({ type: "agenticos:data", n: "nonce-1", bindings: { deals: OK, owners: OK } });
    const asked = parent.postMessage.mock.calls.length;
    load();
    expect(loads).toHaveLength(0);
    expect(parent.postMessage.mock.calls.length).toBe(asked);
  });

  it("listens for no load when it does not ask", () => {
    for (const run of [start({ live: false }), start({}, { orphan: true })]) {
      run.load();
      expect(run.loads).toHaveLength(0);
      expect(run.parent.postMessage).not.toHaveBeenCalled();
    }
  });
});

describe("the artifact data bridge answered at load", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const initial = [
    ["deals", OK],
    ["owners", UNAVAILABLE],
  ];

  it("has its data on load, with nobody asked", async () => {
    const { agenticos, parent } = start({ initial });
    await expect(agenticos.data).resolves.toEqual({ deals: OK, owners: UNAVAILABLE });
    vi.advanceTimersByTime(20_000);
    expect(parent.postMessage).not.toHaveBeenCalled();
  });

  it("calls an onData listener at once and says it subscribes", () => {
    const { agenticos, parent } = start({ initial });
    const seen = vi.fn();
    agenticos.onData(seen);
    expect(seen).toHaveBeenCalledWith({ deals: OK, owners: UNAVAILABLE });
    expect(parent.postMessage).toHaveBeenCalledTimes(1);
    expect(parent.postMessage).toHaveBeenLastCalledWith(...ready(true));
  });

  it("never gives up or resends, and keeps the injected data", async () => {
    const { agenticos, parent } = start({ initial });
    vi.advanceTimersByTime(60_000);
    expect(parent.postMessage).not.toHaveBeenCalled();
    await expect(agenticos.data).resolves.toEqual({ deals: OK, owners: UNAVAILABLE });
  });

  it("still takes a later answer - a refresh - and calls every listener", async () => {
    const { agenticos, dispatch } = start({ initial });
    const seen = vi.fn();
    agenticos.onData(seen);
    const fresh = { ...OK, count: 2 };
    dispatch({ type: "agenticos:data", n: "nonce-1", bindings: { deals: fresh, owners: OK } });
    expect(seen).toHaveBeenCalledTimes(2);
    expect(seen).toHaveBeenLastCalledWith({ deals: fresh, owners: OK });
    // `data` is the first answer: the one written in.
    await expect(agenticos.data).resolves.toEqual({ deals: OK, owners: UNAVAILABLE });
  });

  it("ignores a later answer from another window or nonce", () => {
    const { agenticos, dispatch } = start({ initial });
    const seen = vi.fn();
    agenticos.onData(seen);
    dispatch({ type: "agenticos:data", n: "nonce-1", bindings: { deals: OK } }, {});
    dispatch({ type: "agenticos:data", n: "nonce-0", bindings: { deals: OK } });
    expect(seen).toHaveBeenCalledTimes(1);
  });

  it("says ready once the page has loaded, so the console knows it listens", () => {
    const { agenticos, parent, load } = start({ initial });
    agenticos.onData(vi.fn());
    load();
    expect(parent.postMessage).toHaveBeenCalledTimes(2);
    expect(parent.postMessage).toHaveBeenLastCalledWith(...ready(true));
  });

  it("keeps a name such as __proto__ an own key, and fills a missing one unavailable", async () => {
    const { agenticos } = start({
      names: ["deals", "owners", "__proto__"],
      initial: [["deals", OK], ["__proto__", OK], ["undeclared", OK], "not a pair", [3, OK]],
    });
    const data = await agenticos.data;
    expect(Object.keys(data)).toEqual(["deals", "owners", "__proto__"]);
    expect(Object.getPrototypeOf(data)).toBe(Object.prototype);
    expect(Object.getOwnPropertyDescriptor(data, "__proto__")?.value).toEqual(OK);
    expect(data.owners).toEqual(UNAVAILABLE);
    expect("undeclared" in data).toBe(false);
  });

  it("is answered at load even without a parent or when not live", async () => {
    for (const run of [start({ initial }, { orphan: true }), start({ initial, live: false })]) {
      await expect(run.agenticos.data).resolves.toEqual({ deals: OK, owners: UNAVAILABLE });
      expect(run.listeners).toHaveLength(0);
      expect(run.parent.postMessage).not.toHaveBeenCalled();
    }
  });

  it("asks as before when the page carries no initial data", () => {
    const { parent } = start({ initial: undefined });
    expect(parent.postMessage).toHaveBeenLastCalledWith(...ready(false));
  });
});

describe("the artifact actions bridge", () => {
  const request = (parent: Parent, at = 0) =>
    parent.postMessage.mock.calls.at(at)?.[0] as {
      type: string;
      n: string;
      id: string;
      action: string;
      input: unknown;
    };
  const event = (id: string, rest: Record<string, unknown>) => ({
    type: "agenticos:run-event",
    n: "nonce-1",
    id,
    ...rest,
  });
  const started = (config: Partial<BridgeConfig> = {}) => {
    const page = start({ live: false, actions: true, ...config });
    const pending = page.agenticos.run("Send report", { to: "a" });
    return { ...page, pending, id: request(page.parent).id };
  };

  it("rejects at once and posts nothing when the page may not run actions", async () => {
    for (const config of [{ actions: false }, {}] as Partial<BridgeConfig>[]) {
      const { agenticos, parent } = start({ live: false, ...config });
      await expect(agenticos.run("Send")).rejects.toThrow(/^unavailable$/);
      expect(parent.postMessage).not.toHaveBeenCalled();
    }
    const orphan = start({ live: false, actions: true }, { orphan: true });
    await expect(orphan.agenticos.run("Send")).rejects.toThrow(/^unavailable$/);
  });

  it("rejects a call that is not an action name and an input object", async () => {
    const { agenticos, parent } = start({ live: false, actions: true });
    await expect(agenticos.run("")).rejects.toThrow(/^unknown_action$/);
    await expect(agenticos.run(3)).rejects.toThrow(/^unknown_action$/);
    await expect(agenticos.run("Send", [1])).rejects.toThrow(/^invalid_input$/);
    await expect(agenticos.run("Send", null)).rejects.toThrow(/^invalid_input$/);
    expect(parent.postMessage).not.toHaveBeenCalled();
  });

  it("posts the request under the nonce, with an empty input by default", () => {
    const { agenticos, parent } = start({ live: false, actions: true });
    void agenticos.run("Send");
    void agenticos.run("Send", { to: "a" });
    expect(parent.postMessage).toHaveBeenNthCalledWith(
      1,
      { type: "agenticos:run", n: "nonce-1", id: "r1", action: "Send", input: {} },
      "*",
    );
    expect(request(parent, 1)).toMatchObject({ id: "r2", input: { to: "a" } });
  });

  it("rejects when the input cannot be cloned to the parent", async () => {
    const { agenticos, parent } = start({ live: false, actions: true });
    parent.postMessage.mockImplementation(() => {
      throw new Error("DataCloneError");
    });
    await expect(agenticos.run("Send", { f: 1 })).rejects.toThrow(/^invalid_input$/);
  });

  it("resolves with the finished run and tells listeners each change", async () => {
    const { agenticos, dispatch, pending, id } = started();
    const seen: unknown[] = [];
    agenticos.onRun((progress) => seen.push(progress));
    dispatch(event(id, { event: "progress", status: "running", finished: false }));
    dispatch(
      event(id, {
        event: "progress",
        status: "completed",
        finished: true,
        output_text: "done",
        output_structured: { a: 1 },
      }),
    );
    await expect(pending).resolves.toEqual({
      status: "completed",
      output_text: "done",
      output_structured: { a: 1 },
      error_message: null,
      paused: false,
      run_path: null,
    });
    expect(seen).toHaveLength(2);
    expect(seen[0]).toMatchObject({
      id,
      action: "Send report",
      status: "running",
      finished: false,
    });
    // Settled: a later event for it is ignored.
    dispatch(event(id, { event: "progress", status: "running" }));
    expect(seen).toHaveLength(2);
  });

  it("settles a run the console stopped following, with its last projection", async () => {
    const { agenticos, dispatch, pending, id } = started();
    const seen: unknown[] = [];
    agenticos.onRun((progress) => seen.push(progress));
    dispatch(event(id, { event: "progress", status: "waiting", paused: true, settled: true }));
    await expect(pending).resolves.toMatchObject({ status: "waiting", paused: true });
    expect(seen[0]).toMatchObject({ finished: false, paused: true });
  });

  it("carries a paused run's link and a failed run's short error", async () => {
    const { dispatch, pending, id } = started();
    dispatch(
      event(id, {
        event: "progress",
        status: "waiting",
        paused: true,
        run_path: "/runs/1",
        output_structured: [1],
        error_message: 4,
      }),
    );
    dispatch(
      event(id, { event: "progress", status: "failed", finished: true, error_message: "boom" }),
    );
    await expect(pending).resolves.toMatchObject({
      status: "failed",
      error_message: "boom",
      paused: false,
      output_structured: null,
    });
  });

  it("rejects when the console says so, with its reason or a default", async () => {
    const first = started();
    first.dispatch(event(first.id, { event: "rejected", reason: "cancelled" }));
    await expect(first.pending).rejects.toThrow("cancelled");
    const second = started();
    second.dispatch(event(second.id, { event: "rejected" }));
    await expect(second.pending).rejects.toThrow("rejected");
  });

  it("carries what did not fit on an invalid_input rejection, as plain strings", async () => {
    const { pending, dispatch, id } = started();
    dispatch(
      event(id, {
        event: "rejected",
        reason: "invalid_input",
        problems: [{ field: "to", kind: "required" }, null],
      }),
    );
    const error = (await pending.catch((caught: unknown) => caught)) as Error & {
      problems: unknown;
    };
    expect(error.message).toBe("invalid_input");
    expect(error.problems).toEqual([
      { field: "to", kind: "required" },
      { field: "null", kind: "null" },
    ]);
  });

  it("stops listening for events after the unsubscribe", () => {
    const { agenticos, dispatch, id } = started();
    const seen = vi.fn();
    const off = agenticos.onRun(seen);
    off();
    off();
    dispatch(event(id, { event: "progress", status: "running" }));
    expect(seen).not.toHaveBeenCalled();
  });

  it("ignores events from another frame, under another nonce, or not shaped as one", () => {
    const { agenticos, dispatch, id } = started();
    const seen = vi.fn();
    agenticos.onRun(seen);
    const good = event(id, { event: "progress", status: "running" });
    dispatch(good, { other: true });
    dispatch({ ...good, n: "other" });
    dispatch({ ...good, type: "agenticos:data" });
    dispatch({ ...good, id: "r99" });
    dispatch({ ...good, id: 5 });
    dispatch({ ...good, id: "toString" });
    dispatch({ ...good, event: "other" });
    dispatch(null);
    dispatch("text");
    expect(seen).not.toHaveBeenCalled();
    dispatch(good);
    expect(seen).toHaveBeenCalledTimes(1);
  });
});
