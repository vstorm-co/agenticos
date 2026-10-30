import { describe, expect, it, vi } from "vitest";

import { recordSessionApp } from "./session-app";

const put = vi.hoisted(() => vi.fn(async () => undefined));
vi.mock("@/lib/api-client", () => ({ apiClient: { put } }));

describe("recordSessionApp", () => {
  it("tells the server the app and its version", async () => {
    await recordSessionApp({
      platform: "android",
      version: "0.1.0",
      window: "main",
      vibrancy: false,
    });
    expect(put).toHaveBeenCalledWith("/sessions/current/app", {
      platform: "android",
      version: "0.1.0",
    });
  });
});
