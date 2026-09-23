import { beforeEach, describe, expect, it } from "vitest";

import { emptyTableViewDraft, useTableViewStore } from "./table-view-store";

describe("useTableViewStore", () => {
  beforeEach(() => {
    useTableViewStore.setState({ draft: emptyTableViewDraft(), conflicts: {} });
  });

  it("starts with an empty, unfiltered draft", () => {
    expect(useTableViewStore.getState().draft).toEqual({
      filters: [],
      sort: { by: "created_at", direction: "asc" },
      visibleColumns: null,
      groupBy: null,
    });
  });

  it("replaces the draft wholesale", () => {
    const next = {
      filters: [{ column_id: "c1", op: "eq" as const, value: "x" }],
      sort: { by: "updated_at", direction: "desc" as const },
      visibleColumns: ["c1"],
      groupBy: "c1",
    };

    useTableViewStore.getState().setDraft(next);

    expect(useTableViewStore.getState().draft).toEqual(next);
  });

  it("records a conflict keyed by record id and clears it independently of others", () => {
    const store = useTableViewStore.getState();
    store.setConflict({ recordId: "r1", pendingValues: { c1: "a" }, fieldId: "c1" });
    store.setConflict({ recordId: "r2", pendingValues: { c1: "b" }, fieldId: null });

    expect(Object.keys(useTableViewStore.getState().conflicts).sort()).toEqual(["r1", "r2"]);

    useTableViewStore.getState().clearConflict("r1");

    expect(useTableViewStore.getState().conflicts).toEqual({
      r2: { recordId: "r2", pendingValues: { c1: "b" }, fieldId: null },
    });
  });

  it("a second conflict on the same record replaces the first", () => {
    const store = useTableViewStore.getState();
    store.setConflict({ recordId: "r1", pendingValues: { c1: "a" }, fieldId: "c1" });
    store.setConflict({ recordId: "r1", pendingValues: { c1: "b" }, fieldId: "c1" });

    expect(useTableViewStore.getState().conflicts.r1?.pendingValues).toEqual({ c1: "b" });
  });

  it("reset clears both the draft and every conflict", () => {
    const store = useTableViewStore.getState();
    store.setDraft({
      filters: [],
      sort: { by: "updated_at", direction: "desc" },
      visibleColumns: ["c1"],
      groupBy: null,
    });
    store.setConflict({ recordId: "r1", pendingValues: {}, fieldId: null });

    useTableViewStore.getState().reset();

    expect(useTableViewStore.getState().draft).toEqual(emptyTableViewDraft());
    expect(useTableViewStore.getState().conflicts).toEqual({});
  });
});
