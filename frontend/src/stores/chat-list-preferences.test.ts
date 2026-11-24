import { beforeEach, expect, it } from "vitest";
import { useChatListPreferencesStore as store } from "./chat-sidebar-store";
beforeEach(() => {
  store.setState({ groupedByUser: {} });
  localStorage.removeItem("chat-list-preferences");
});
it("defaults to grouped without carrying another signed-in user's choice", () => {
  expect(store.getState().groupedByUser.alice ?? true).toBe(true);
  store.getState().setGrouped("alice", false);
  expect(store.getState().groupedByUser.alice).toBe(false);
  expect(store.getState().groupedByUser.bob ?? true).toBe(true);
  store.getState().setGrouped("bob", true);
  expect(store.getState().groupedByUser.alice).toBe(false);
});
it("restores a user's grouping choice across reloads", async () => {
  store.getState().setGrouped("alice", false);
  const saved = localStorage.getItem("chat-list-preferences");
  expect(saved).toContain("alice");
  store.setState({ groupedByUser: {} });
  localStorage.setItem("chat-list-preferences", saved!);
  await store.persist.rehydrate();
  expect(store.getState().groupedByUser.alice).toBe(false);
});
