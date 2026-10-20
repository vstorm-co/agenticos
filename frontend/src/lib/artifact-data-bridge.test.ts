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
}

type Bindings = Record<string, unknown>;

interface Agenticos {
  data: Promise<Bindings>;
  onData: (fn: (bindings: Bindings) => void) => void;
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
  filters_dropped: false,
};

const OK = {
  status: "ok",
  records: [{ id: "r1", stage: "</script><img src=x onerror=alert(1)>" }],
  fields: {},
  truncated: false,
  limit: null,
  count: 1,
  filters_dropped: false,
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
