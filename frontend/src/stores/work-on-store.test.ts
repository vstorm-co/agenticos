import { beforeEach, expect, it } from "vitest";
import { useWorkOnStore } from "./work-on-store";

const target = { folder: "/approved", mode: "read_only" } as const;
beforeEach(() =>
  useWorkOnStore.setState({ byConversation: {}, draft: null, draftProjectKey: null }),
);
it("moves a new chat's local choice under its server identity", () => {
  const store = useWorkOnStore.getState();
  store.set(null, target);
  expect(store.targetFor(null)).toEqual(target);
  store.adopt("created");
  expect(store.targetFor(null)).toBeNull();
  expect(store.targetFor("created")).toEqual(target);
  store.set("other", { ...target, folder: "/other" });
  store.set("created", null);
  expect(store.targetFor("created")).toBeNull();
  expect(store.targetFor("other")?.folder).toBe("/other");
});
it("preserves an existing chat's choice when returning to it with an unsent draft", () => {
  const store = useWorkOnStore.getState();
  store.set("existing", target);
  store.set(null, { ...target, folder: "/draft" });
  store.adopt("existing");
  expect(store.targetFor("existing")).toEqual(target);
  expect(store.targetFor(null)?.folder).toBe("/draft");
  store.set(null, null);
  store.adopt("new");
  expect(store.targetFor("new")).toBeNull();
});

it("applies a project default once and keeps an explicit Cloud override", () => {
  const store = useWorkOnStore.getState();
  store.applyProject("alice:org:project", target);
  expect(store.targetFor(null)).toEqual(target);
  store.set(null, null);
  store.applyProject("alice:org:project", target);
  expect(store.targetFor(null)).toBeNull();
  store.applyProject("bob:org:project", { ...target, folder: "/bob" });
  expect(store.targetFor(null)?.folder).toBe("/bob");
  store.resetDraft();
  expect(useWorkOnStore.getState().draftProjectKey).toBeNull();
  expect(store.targetFor(null)).toBeNull();
});
it("adopts the inherited project folder while preserving other conversations", () => {
  const store = useWorkOnStore.getState();
  store.set("existing", { ...target, folder: "/existing" });
  store.applyProject("project", target);
  store.adopt("created");
  expect(store.targetFor("created")).toEqual(target);
  expect(store.targetFor("existing")?.folder).toBe("/existing");
  expect(useWorkOnStore.getState().draftProjectKey).toBeNull();
});
