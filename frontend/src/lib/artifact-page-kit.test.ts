import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/*
 * The page kit runs in the served page, not in the console, so it lives beside
 * the backend that serves it. Read version 3 from there and run it here, in
 * jsdom. Version 2 is served immutable for a year and is never changed, so
 * what version 3 adds is tested against version 3 alone.
 */
const source = readFileSync(
  join(process.cwd(), "..", "backend", "app", "core", "catalog", "artifact_lib", "agenticos-3.js"),
  "utf8",
);

type Render = (data: unknown) => void;

interface Binding {
  status: "ok" | "unavailable";
  records: Record<string, unknown>[];
  fields: Record<string, { label: string; type: string; options?: string[] | null; state: string }>;
  count: number;
  truncated: boolean;
  limit: "records" | "bytes" | null;
}

interface RecordsOptions {
  columns?: string[];
  labels?: Record<string, string>;
  badges?: Record<string, Record<string, string>>;
  format?: Record<string, (value: unknown, record: Record<string, unknown>) => string>;
  text?: Record<string, string>;
}

interface Kit {
  onData: (render: Render) => unknown;
  records: (
    target: string | Element,
    binding?: Binding | null,
    options?: RecordsOptions,
  ) => HTMLTableElement | null;
  icons: (scope?: Element) => void;
  run: (action: string, input?: Record<string, unknown>) => Promise<unknown>;
  onRun: (listener: (event: unknown) => void) => unknown;
}

interface Lucide {
  createIcons: (options: { root: Element | Document; attrs: Record<string, unknown> }) => void;
}

interface PageWindow {
  AO?: Kit;
  agenticos?: {
    onData?: (render: Render) => unknown;
    run?: (action: string, input?: Record<string, unknown>) => Promise<unknown>;
    onRun?: (listener: (event: unknown) => void) => unknown;
  };
  lucide?: Lucide;
}

const page = window as unknown as PageWindow;
const observers: MutationObserver[] = [];

/** The real observer, remembered so each test's kit stops watching afterwards. */
class RecordingObserver extends MutationObserver {
  constructor(callback: MutationCallback) {
    super(callback);
    observers.push(this);
  }
}

/** Lucide's own move, cut down: every waiting `[data-lucide]` under `root` becomes an `<svg>`. */
function fakeLucide(): Lucide & { createIcons: ReturnType<typeof vi.fn> } {
  return {
    createIcons: vi.fn(({ root }: { root: Element | Document }) => {
      root.querySelectorAll("[data-lucide]").forEach((icon) => {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("data-lucide", icon.getAttribute("data-lucide") ?? "");
        icon.replaceWith(svg);
      });
    }),
  };
}

function load(): Kit {
  new Function(source)();
  if (!page.AO) throw new Error("the kit did not define window.AO");
  return page.AO;
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 20));

function binding(overrides: Partial<Binding> = {}): Binding {
  return {
    status: "ok",
    records: [],
    fields: {},
    count: 0,
    truncated: false,
    limit: null,
    ...overrides,
  };
}

const TICKETS = binding({
  records: [
    { id: "r1", title: "Printer on fire", status: "Open", hours: 1234.5, due: "2026-10-21" },
    { id: "r2", title: "Badge reader", status: "Closed", hours: 2, due: null },
  ],
  fields: {
    title: { label: "Title", type: "text", state: "ok" },
    status: { label: "Status", type: "single_select", options: ["Open", "Closed"], state: "ok" },
    hours: { label: "Hours", type: "number", state: "ok" },
    due: { label: "Due", type: "date", state: "ok" },
    gone: { label: "gone", type: "text", state: "missing" },
  },
  count: 2,
});

beforeEach(() => {
  vi.stubGlobal("MutationObserver", RecordingObserver);
  document.documentElement.lang = "en";
  document.body.innerHTML = '<div id="tickets"></div>';
});

afterEach(() => {
  observers.splice(0).forEach((observer) => observer.disconnect());
  vi.unstubAllGlobals();
  delete page.AO;
  delete page.agenticos;
  delete page.lucide;
  document.body.innerHTML = "";
});

describe("AO.onData", () => {
  it("hands the render to the bridge, even one that arrived after the kit", () => {
    const kit = load();
    const onData = vi.fn(() => "subscribed");
    page.agenticos = { onData };
    const render = vi.fn();

    expect(kit.onData(render)).toBe("subscribed");
    expect(onData).toHaveBeenCalledWith(render);
  });

  it("says why when the page was opened without its data bridge", () => {
    expect(() => load().onData(vi.fn())).toThrow(/no data bridge/);
  });
});

describe("AO.run and AO.onRun", () => {
  it("hand the call to the platform's bridge, looked up when called", async () => {
    const kit = load();
    const run = vi.fn(() => Promise.resolve({ status: "completed" }));
    const onRun = vi.fn(() => "off");
    page.agenticos = { run, onRun };
    const listener = vi.fn();

    await expect(kit.run("Send", { to: "a" })).resolves.toEqual({ status: "completed" });
    expect(run).toHaveBeenCalledWith("Send", { to: "a" });
    expect(kit.onRun(listener)).toBe("off");
    expect(onRun).toHaveBeenCalledWith(listener);
  });

  it("say why when the page was opened without the action bridge", async () => {
    const kit = load();
    await expect(kit.run("Send")).rejects.toThrow(/^unavailable$/);
    expect(() => kit.onRun(vi.fn())).toThrow(/no action bridge/);
  });
});

describe("AO.records", () => {
  it("draws a loading line before the first data, and marks the target busy", () => {
    load().records("#tickets");
    const target = document.getElementById("tickets")!;

    expect(target.getAttribute("aria-busy")).toBe("true");
    expect(target.querySelector(".ao-table-wrap > .ao-loading")?.textContent).toBe("Loading…");
  });

  it("draws an unavailable binding as no data, in the page's own words", () => {
    const table = load().records("#tickets", binding({ status: "unavailable" }), {
      text: { unavailable: "Brak danych." },
    });

    expect(table).toBeNull();
    const target = document.getElementById("tickets")!;
    expect(target.querySelector(".ao-empty")?.textContent).toBe("Brak danych.");
    expect(target.hasAttribute("aria-busy")).toBe(false);
  });

  it("draws an empty view as a message, not an empty table", () => {
    load().records("#tickets", binding());

    const target = document.getElementById("tickets")!;
    expect(target.querySelector("table")).toBeNull();
    expect(target.querySelector(".ao-empty")?.textContent).toBe("Nothing to show.");
  });

  it("draws the records as a table with a head and a body, columns from the fields", () => {
    const table = load().records("#tickets", TICKETS, { badges: { status: { Open: "warning" } } })!;

    const headings = [...table.tHead!.rows[0]!.cells].map((cell) => [
      cell.textContent,
      cell.className,
    ]);
    expect(headings).toEqual([
      ["Title", ""],
      ["Status", ""],
      ["Hours", "ao-num"],
      ["Due", "ao-num"],
    ]);
    expect(table.className).toBe("ao-table");
    expect(table.parentElement?.className).toBe("ao-table-wrap");
    const [first, second] = table.tBodies[0]!.rows;
    expect(first!.cells[0]!.className).toBe("ao-strong");
    expect(first!.cells[2]!.textContent).toBe("1,234.5");
    expect(first!.cells[2]!.className).toBe("ao-num");
    expect(first!.cells[3]!.textContent).toBe("Oct 21, 2026");
    expect(first!.cells[1]!.innerHTML).toBe('<span class="ao-badge ao-badge-warning">Open</span>');
    expect(second!.cells[1]!.innerHTML).toBe('<span class="ao-badge">Closed</span>');
    expect(second!.cells[3]!.textContent).toBe("");
  });

  it("writes every value and heading as text, so markup in a record stays text", () => {
    const hostile = "</td><img src=x onerror=alert(1)>";
    const table = load().records(
      "#tickets",
      binding({
        records: [{ id: "r1", title: hostile, status: hostile, tags: [hostile] }],
        fields: {
          title: { label: hostile, type: "text", state: "ok" },
          status: { label: "Status", type: "single_select", state: "ok" },
          tags: { label: "Tags", type: "multi_select", state: "ok" },
        },
        count: 1,
      }),
      { badges: { status: { [hostile]: '" onclick="alert(1)' } } },
    )!;

    expect(table.querySelector("img")).toBeNull();
    expect(table.querySelector("[onclick]")).toBeNull();
    expect(table.tHead!.rows[0]!.cells[0]!.textContent).toBe(hostile);
    const cells = table.tBodies[0]!.rows[0]!.cells;
    expect(cells[0]!.textContent).toBe(hostile);
    expect(cells[1]!.querySelector(".ao-badge")?.className).toBe("ao-badge");
    expect(cells[1]!.textContent).toBe(hostile);
    expect(cells[2]!.textContent).toBe(hostile);
  });

  it("says when the list is cut", () => {
    load().records("#tickets", { ...TICKETS, truncated: true, limit: "records" });

    const notes = [...document.querySelectorAll("#tickets > .ao-note")].map(
      (note) => note.textContent,
    );
    expect(notes).toEqual(["Showing the first 2 records."]);
  });

  it("draws into a table wrap it is given, notes included, and draws afresh each time", () => {
    document.body.innerHTML = '<div class="ao-table-wrap" id="wrap"></div>';
    const kit = load();
    kit.records("#wrap", { ...TICKETS, truncated: true });
    kit.records("#wrap", { ...TICKETS, truncated: true });

    const wrap = document.getElementById("wrap")!;
    expect(wrap.querySelectorAll("table")).toHaveLength(1);
    expect(wrap.querySelectorAll(":scope > .ao-note")).toHaveLength(1);
    expect(wrap.querySelector(".ao-table-wrap")).toBeNull();
  });

  it("takes the columns, headings and formatting the page asks for", () => {
    const table = load().records("#tickets", TICKETS, {
      columns: ["hours", "title"],
      labels: { hours: "Czas" },
      format: { title: (value) => `#${String(value)}` },
    })!;

    expect([...table.tHead!.rows[0]!.cells].map((cell) => cell.textContent)).toEqual([
      "Czas",
      "Title",
    ]);
    expect(table.tBodies[0]!.rows[0]!.cells[1]!.textContent).toBe("#Printer on fire");
  });

  it("falls back to the record's own keys when the binding names no fields", () => {
    const table = load().records(
      "#tickets",
      binding({
        records: [{ id: "r1", name: "Ada", done: true, links: [{ id: "x", label: "Acme" }] }],
        count: 1,
      }),
    )!;

    expect([...table.tHead!.rows[0]!.cells].map((cell) => cell.textContent)).toEqual([
      "name",
      "done",
      "links",
    ]);
    expect([...table.tBodies[0]!.rows[0]!.cells].map((cell) => cell.textContent)).toEqual([
      "Ada",
      "Yes",
      "Acme",
    ]);
  });

  it("refuses a target that is not on the page, by name", () => {
    expect(() => load().records("#nowhere", TICKETS)).toThrow(/#nowhere/);
  });
});

describe("icons", () => {
  it("draws an icon a script adds after the page loaded, only where it was added", async () => {
    const lucide = fakeLucide();
    page.lucide = lucide;
    load();
    lucide.createIcons.mockClear();

    const row = document.createElement("p");
    row.innerHTML = '<i data-lucide="circle-check"></i> Done';
    document.getElementById("tickets")!.append(row);
    await settle();

    expect(row.querySelector("svg[data-lucide='circle-check']")).not.toBeNull();
    expect(lucide.createIcons).toHaveBeenCalledTimes(1);
    expect(lucide.createIcons.mock.calls[0]![0]).toMatchObject({
      root: row,
      attrs: { "stroke-width": 1.75, "aria-hidden": "true" },
    });
  });

  it("settles after drawing, rather than redrawing the icons it drew", async () => {
    const lucide = fakeLucide();
    page.lucide = lucide;
    load();
    lucide.createIcons.mockClear();

    const target = document.getElementById("tickets")!;
    target.innerHTML = '<i data-lucide="a"></i><i data-lucide="b"></i>';
    await settle();
    await settle();

    expect(lucide.createIcons).toHaveBeenCalledTimes(1);
    expect(target.querySelectorAll("svg[data-lucide]")).toHaveLength(2);
  });

  it("warns once at load when the page uses icons but never loaded Lucide", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    document.body.innerHTML = '<i data-lucide="star"></i>';
    load();

    expect(warn).toHaveBeenCalledWith(expect.stringContaining("lib/lucide-1.46.0.min.js"));
    warn.mockRestore();
  });
});
