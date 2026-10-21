import { beforeEach, describe, expect, it } from "vitest";

import { useVoiceGlowStore } from "./voice-glow-store";

describe("useVoiceGlowStore", () => {
  beforeEach(() => {
    useVoiceGlowStore.setState({ style: "subtle" });
    localStorage.clear();
  });

  it("starts subtle, so a fresh browser does not get the light show", () => {
    expect(useVoiceGlowStore.getInitialState().style).toBe("subtle");
  });

  it("keeps the person's choice in this browser", () => {
    useVoiceGlowStore.getState().setStyle("off");

    expect(useVoiceGlowStore.getState().style).toBe("off");
    const stored = JSON.parse(localStorage.getItem("voice-glow-storage") ?? "{}");
    expect(stored.state.style).toBe("off");
  });
});
