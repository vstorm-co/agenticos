// @vitest-environment node
import { describe, expect, it } from "vitest";

import { invokeShell, readShellInfo } from "./shell";
import { currentWindow } from "./window";

/** On the server there is no window at all, and nothing here may reach for one. */
describe("the desktop modules on the server", () => {
  it("find no shell and no window", async () => {
    expect(readShellInfo()).toBeNull();
    await expect(invokeShell("desktop_state")).rejects.toMatchObject({ failure: "unavailable" });
    expect(() => currentWindow()).toThrow("unavailable: window");
  });
});
