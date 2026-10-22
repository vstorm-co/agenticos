import { afterEach, describe, expect, it, vi } from "vitest";

import { updateWidget } from "./widget";

afterEach(() => {
  delete window.__TAURI__;
});

describe("updateWidget", () => {
  it("hands the app the counts", async () => {
    const invoke = vi.fn(async () => null);
    window.__TAURI__ = { core: { invoke }, event: { listen: vi.fn() } };
    await updateWidget({ approvals: 2, running: 1 });
    expect(invoke).toHaveBeenCalledWith("update_widget", { glance: { approvals: 2, running: 1 } });
  });
});
