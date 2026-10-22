import { beforeEach, describe, expect, it } from "vitest";

import { useVoiceCallStore } from "./voice-call-store";

describe("voice call store", () => {
  beforeEach(() => useVoiceCallStore.setState({ pushToTalk: false }));

  it("is hands-free by default and remembers push-to-talk", () => {
    expect(useVoiceCallStore.getState().pushToTalk).toBe(false);
    useVoiceCallStore.getState().setPushToTalk(true);
    expect(useVoiceCallStore.getState().pushToTalk).toBe(true);
    expect(localStorage.getItem("voice-call-storage")).toContain('"pushToTalk":true');
  });
});
