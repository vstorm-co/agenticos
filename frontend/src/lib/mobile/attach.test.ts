import { afterEach, describe, expect, it, vi } from "vitest";

import { offerRecentPhoto, openAttachSheet } from "./attach";

afterEach(() => {
  delete window.__TAURI__;
});

describe("the phone app's attach commands", () => {
  it("open the sheet and ask for a recent photo, reading what comes back", async () => {
    const invoke = vi.fn(async (command: string) =>
      command === "attach_sheet"
        ? {
            text: "",
            files: [{ name: "a.png", mimeType: "image/png", data: btoa("x") }],
            refused: [],
          }
        : null,
    );
    window.__TAURI__ = { core: { invoke }, event: { listen: vi.fn() } };
    expect((await openAttachSheet())?.files[0]?.name).toBe("a.png");
    expect(await offerRecentPhoto()).toBeNull();
    expect(invoke.mock.calls.map(([command]) => command)).toEqual([
      "attach_sheet",
      "offer_recent_photo",
    ]);
  });
});
