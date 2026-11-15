import { describe, expect, it } from "vitest";

import { deviceSetupState } from "./use-desktop-setup";

describe("deviceSetupState", () => {
  it("asks for a link only when the computer is not linked", () => {
    expect(deviceSetupState({ data: { linked: false, connected: false }, error: null })).toBe(
      "missing",
    );
  });

  it("is checking, not missing, while a linked computer reconnects", () => {
    expect(deviceSetupState({ data: { linked: true, connected: false }, error: null })).toBe(
      "checking",
    );
  });

  it("is ready once linked and connected, checking before the answer, error on failure", () => {
    expect(deviceSetupState({ data: { linked: true, connected: true }, error: null })).toBe(
      "ready",
    );
    expect(deviceSetupState({ data: undefined, error: null })).toBe("checking");
    expect(deviceSetupState({ data: undefined, error: new Error("shell") })).toBe("error");
  });
});
