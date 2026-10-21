import { beforeEach, describe, expect, it } from "vitest";

import { useComposerIntentStore } from "./composer-intent-store";

beforeEach(() => useComposerIntentStore.setState({ intent: null }));

describe("useComposerIntentStore", () => {
  it("holds a shortcut's request until the chat clears it", () => {
    useComposerIntentStore.getState().request("call");
    expect(useComposerIntentStore.getState().intent).toBe("call");
    useComposerIntentStore.getState().request("dictate");
    expect(useComposerIntentStore.getState().intent).toBe("dictate");
    useComposerIntentStore.getState().clear();
    expect(useComposerIntentStore.getState().intent).toBeNull();
  });
});
