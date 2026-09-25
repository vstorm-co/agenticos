import { beforeEach, describe, expect, it } from "vitest";

import { useTableViewStore } from "./table-view-store";

describe("useTableViewStore", () => {
  beforeEach(() => {
    useTableViewStore.setState({ conflicts: {} });
  });

  it("records a conflict keyed by record id and field", () => {
    const store = useTableViewStore.getState();
    store.setConflict({ recordId: "r1", pendingValues: { c1: "a" }, fieldId: "c1" });
    store.setConflict({ recordId: "r2", pendingValues: { c1: "b" }, fieldId: null });

    expect(Object.keys(useTableViewStore.getState().conflicts).sort()).toEqual(["r1", "r2"]);
    expect(useTableViewStore.getState().conflicts.r1?.c1).toEqual({
      recordId: "r1",
      pendingValues: { c1: "a" },
      fieldId: "c1",
    });
  });

  it("keeps conflicts on two different records independent", () => {
    const store = useTableViewStore.getState();
    store.setConflict({ recordId: "r1", pendingValues: { c1: "a" }, fieldId: "c1" });
    store.setConflict({ recordId: "r2", pendingValues: { c1: "b" }, fieldId: null });

    useTableViewStore.getState().clearConflict("r1", "c1");

    expect(useTableViewStore.getState().conflicts.r1).toBeUndefined();
    expect(useTableViewStore.getState().conflicts.r2).toBeDefined();
  });

  it("keeps a conflict on one field of a record independent of a conflict on another field of the same record", () => {
    // The regression this guards: a second field of the same record going into
    // conflict (or landing successfully) used to overwrite - or clear - the
    // *whole record's* single conflict entry, dropping whatever the first
    // field's own banner and pending value were, even though the two fields
    // were never in a race with each other.
    const store = useTableViewStore.getState();
    store.setConflict({ recordId: "r1", pendingValues: { c1: "a" }, fieldId: "c1" });
    store.setConflict({ recordId: "r1", pendingValues: { c2: "b" }, fieldId: "c2" });

    expect(useTableViewStore.getState().conflicts.r1?.c1?.pendingValues).toEqual({ c1: "a" });
    expect(useTableViewStore.getState().conflicts.r1?.c2?.pendingValues).toEqual({ c2: "b" });

    useTableViewStore.getState().clearConflict("r1", "c2");

    expect(useTableViewStore.getState().conflicts.r1?.c1?.pendingValues).toEqual({ c1: "a" });
    expect(useTableViewStore.getState().conflicts.r1?.c2).toBeUndefined();
  });

  it("clears the record entirely once its last field conflict is cleared", () => {
    const store = useTableViewStore.getState();
    store.setConflict({ recordId: "r1", pendingValues: { c1: "a" }, fieldId: "c1" });

    useTableViewStore.getState().clearConflict("r1", "c1");

    expect(useTableViewStore.getState().conflicts.r1).toBeUndefined();
  });

  it("clearing a field that has no conflict is a no-op", () => {
    const store = useTableViewStore.getState();
    store.setConflict({ recordId: "r1", pendingValues: { c1: "a" }, fieldId: "c1" });

    useTableViewStore.getState().clearConflict("r1", "c2");

    expect(useTableViewStore.getState().conflicts.r1?.c1).toBeDefined();
  });

  it("a second conflict on the same record and field replaces the first", () => {
    const store = useTableViewStore.getState();
    store.setConflict({ recordId: "r1", pendingValues: { c1: "a" }, fieldId: "c1" });
    store.setConflict({ recordId: "r1", pendingValues: { c1: "b" }, fieldId: "c1" });

    expect(useTableViewStore.getState().conflicts.r1?.c1?.pendingValues).toEqual({ c1: "b" });
  });

  it("reset clears every conflict", () => {
    const store = useTableViewStore.getState();
    store.setConflict({ recordId: "r1", pendingValues: {}, fieldId: null });

    useTableViewStore.getState().reset();

    expect(useTableViewStore.getState().conflicts).toEqual({});
  });
});
