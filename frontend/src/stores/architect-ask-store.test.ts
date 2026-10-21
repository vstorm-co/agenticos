import { describe, expect, it } from "vitest";

import { useArchitectAskStore } from "./architect-ask-store";

describe("useArchitectAskStore", () => {
  it("numbers each question so the same words asked twice are asked twice", () => {
    useArchitectAskStore.getState().ask("Draft an agent");
    const first = useArchitectAskStore.getState().asked;
    useArchitectAskStore.getState().ask("Draft an agent");
    expect(useArchitectAskStore.getState().asked).toEqual({
      id: (first?.id ?? 0) + 1,
      text: "Draft an agent",
    });
    useArchitectAskStore.getState().clear();
    expect(useArchitectAskStore.getState().asked).toBeNull();
  });
});
