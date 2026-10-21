import { afterEach, describe, expect, it, vi } from "vitest";

import { ShellError } from "@/lib/desktop/shell";

import {
  endActivity,
  parseActivityAsk,
  planActivities,
  showActivity,
  takeActivityAction,
  type LiveActivity,
} from "./live-activities";

const run: LiveActivity = {
  id: "run:r1",
  kind: "run",
  title: "Support is working",
  body: "",
  path: "/runs?run=r1",
  startedAt: 1,
};

function withShell(invoke: (command: string, args?: unknown) => unknown) {
  window.__TAURI__ = { core: { invoke: vi.fn(invoke) }, event: { listen: vi.fn() } };
}

afterEach(() => {
  delete window.__TAURI__;
});

describe("parseActivityAsk", () => {
  it("reads nothing waiting, a page to open and a decision", () => {
    expect(parseActivityAsk(null)).toBeNull();
    expect(parseActivityAsk({ kind: "open", path: "/runs" })).toEqual({
      kind: "open",
      path: "/runs",
    });
    expect(parseActivityAsk({ kind: "decide", approval_id: "ap1", approved: false })).toEqual({
      kind: "decide",
      approval_id: "ap1",
      approved: false,
    });
  });

  it("refuses a page outside the console and any shape it does not know", () => {
    for (const value of [
      { kind: "open", path: "https://evil.example" },
      { kind: "decide", approval_id: "ap1" },
      { kind: "delete" },
      "open",
      undefined,
    ]) {
      expect(() => parseActivityAsk(value)).toThrow(ShellError);
    }
  });
});

describe("the app's commands", () => {
  it("show, end and take an activity through the app", async () => {
    const calls: unknown[] = [];
    withShell((command, args) => {
      calls.push([command, args]);
      return command === "take_activity_action" ? { kind: "open", path: "/runs" } : null;
    });
    await showActivity(run);
    await endActivity("run:r1");
    await expect(takeActivityAction()).resolves.toEqual({ kind: "open", path: "/runs" });
    expect(calls).toEqual([
      ["show_activity", { activity: run }],
      ["end_activity", { id: "run:r1" }],
      ["take_activity_action", undefined],
    ]);
  });
});

describe("planActivities", () => {
  it("shows what is new or changed and ends what is over", () => {
    const shown = new Map([
      ["run:r1", JSON.stringify(run)],
      ["run:gone", "{}"],
    ]);
    const renamed = { ...run, title: "Sales is working" };
    const fresh = { ...run, id: "run:r2" };
    expect(planActivities(shown, [run, fresh])).toEqual({ show: [fresh], end: ["run:gone"] });
    expect(planActivities(shown, [renamed])).toEqual({
      show: [renamed],
      end: ["run:gone"],
    });
  });
});
