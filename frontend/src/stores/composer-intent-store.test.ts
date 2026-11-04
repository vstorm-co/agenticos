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

describe("what another app shared", () => {
  it("is held for the chat's next message until it takes it", () => {
    const shared = { id: 1, files: [], text: "look" };
    useComposerIntentStore.getState().share(shared);
    expect(useComposerIntentStore.getState().shared).toBe(shared);
    useComposerIntentStore.getState().clearShared();
    expect(useComposerIntentStore.getState().shared).toBeNull();
  });
});
