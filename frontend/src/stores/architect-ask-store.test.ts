import { beforeEach, describe, expect, it } from "vitest";

import { architectAskMatchesScope, useArchitectAskStore } from "./architect-ask-store";

beforeEach(() => {
  useArchitectAskStore.setState({ request: null });
});

describe("useArchitectAskStore", () => {
  it("carries account scope and rejects delivery after a user or organization change", () => {
    const scope = { userId: "user-1", orgId: "org-1" };
    useArchitectAskStore.getState().ask("Read my selected account", scope);
    const request = useArchitectAskStore.getState().request!;
    expect(request.scope).toEqual(scope);
    expect(architectAskMatchesScope(request, scope)).toBe(true);
    expect(architectAskMatchesScope(request, { ...scope, userId: "user-2" })).toBe(false);
    expect(architectAskMatchesScope(request, { ...scope, orgId: "org-2" })).toBe(false);
    expect(architectAskMatchesScope(request, { ...scope, userId: null })).toBe(false);
    useArchitectAskStore.getState().ask("Legacy ask");
    expect(architectAskMatchesScope(useArchitectAskStore.getState().request!, scope)).toBe(true);
  });

  it("makes the same words asked twice two asks", () => {
    useArchitectAskStore.getState().ask("Make an agent");
    const first = useArchitectAskStore.getState().request;
    useArchitectAskStore.getState().ask("Make an agent");
    const second = useArchitectAskStore.getState().request;

    expect(second?.text).toBe("Make an agent");
    expect(second?.id).not.toBe(first?.id);
    expect(second?.draft).toBe(false);
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
