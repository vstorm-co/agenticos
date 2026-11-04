import { beforeEach, describe, expect, it } from "vitest";

import { useArchitectAskStore } from "./architect-ask-store";

beforeEach(() => {
  useArchitectAskStore.setState({ request: null });
});

describe("useArchitectAskStore", () => {
  it("makes the same words asked twice two asks", () => {
    useArchitectAskStore.getState().ask("Make an agent");
    const first = useArchitectAskStore.getState().request;
    useArchitectAskStore.getState().ask("Make an agent");
    const second = useArchitectAskStore.getState().request;

    expect(second?.text).toBe("Make an agent");
    expect(second?.id).not.toBe(first?.id);
  });

  it("drops an answered ask, and never a newer one asked meanwhile", () => {
    useArchitectAskStore.getState().ask("first");
    const first = useArchitectAskStore.getState().request!;
    useArchitectAskStore.getState().ask("second");

    useArchitectAskStore.getState().answered(first.id);
    expect(useArchitectAskStore.getState().request?.text).toBe("second");

    useArchitectAskStore.getState().answered(useArchitectAskStore.getState().request!.id);
    expect(useArchitectAskStore.getState().request).toBeNull();
  });

  it("gives an ask after an answered one a new id", () => {
    useArchitectAskStore.getState().ask("first");
    const first = useArchitectAskStore.getState().request!;
    useArchitectAskStore.getState().answered(first.id);

    useArchitectAskStore.getState().ask("second");

    expect(useArchitectAskStore.getState().request!.id).toBeGreaterThan(first.id);
  });
});
