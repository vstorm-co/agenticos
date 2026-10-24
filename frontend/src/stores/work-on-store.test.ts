import { beforeEach, expect, it } from "vitest";
import { useWorkOnStore } from "./work-on-store";

const target = { folder: "/approved", mode: "read_only" } as const;
beforeEach(() => useWorkOnStore.setState({ byConversation: {}, draft: null }));
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
