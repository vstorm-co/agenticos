import { useChatControlsStore } from "@/stores/chat-controls-store";
import { beforeEach, expect, it } from "vitest";
import { useWorkOnStore } from "./work-on-store";

const target = { folder: "/approved", mode: "read_only" } as const;
beforeEach(() => {
  useChatControlsStore.setState({ byScope: {} });
  useWorkOnStore.setState({
    byConversation: {},
    draft: null,
    draftProjectKey: null,
    computerByConversation: {},
    draftComputer: undefined,
    browserByConversation: {},
    draftBrowser: undefined,
  });
});
it("moves a new chat's local choice under its server identity", () => {
  const store = useWorkOnStore.getState();
  store.set(null, target);
  expect(store.targetFor(null)).toEqual(target);
  store.adopt("created");
  expect(store.targetFor(null)).toEqual(target);
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

it("adopts a browser-only choice and preserves it when the sandbox returns to Cloud", () => {
  const store = useWorkOnStore.getState();
  store.setBrowser(null, true);
  store.adopt("browser-only");
  expect(store.targetFor("browser-only")).toBeNull();
  expect(store.browserFor("browser-only")).toBe(true);
  store.set("browser-only", target);
  store.set("browser-only", null);
  expect(store.browserFor("browser-only")).toBe(true);
  store.setBrowser("browser-only", false);
  expect(store.browserFor("browser-only")).toBe(false);
  expect(store.browserFor("new")).toBe(false);
  store.setBrowser(null, true);
  store.resetDraft();
  expect(store.browserFor(null)).toBe(true);
});

it("adopts an independent screen choice and keeps it when files return to Cloud", () => {
  const store = useWorkOnStore.getState();
  store.setComputer(null, true);
  store.adopt("screen-only");
  expect(store.computerFor("screen-only")).toBe(true);
  expect(store.targetFor("screen-only")).toBeNull();
  store.set("screen-only", target);
  store.set("screen-only", null);
  expect(store.computerFor("screen-only")).toBe(true);
  expect(store.computerFor(null)).toBe(true);
  store.setComputer("screen-only", false);
  expect(store.computerFor("screen-only")).toBe(false);
});

it("remembers tool choices and folder defaults for the next conversation", () => {
  const store = useWorkOnStore.getState();
  store.set("one", target);
  store.setBrowser("one", true);
  store.setComputer("one", true);
  store.resetDraft();
  expect(store.targetFor(null)?.folder).toBe(target.folder);
  expect(store.browserFor(null)).toBe(true);
  expect(store.computerFor(null)).toBe(true);
  store.applyProject("different-project", null);
  expect(store.targetFor(null)).toBeNull();
});
it("never carries a whole-computer consent token to a new conversation", () => {
  const store = useWorkOnStore.getState();
  store.set("one", { folder: "/home", mode: "full_access", computer_grant: "one-chat-only" });
  store.resetDraft();
  expect(store.targetFor(null)).toBeNull();
  expect(store.targetFor("one")?.computer_grant).toBe("one-chat-only");
});

it("files an explicit project Cloud default instead of falling back to an unrelated folder", () => {
  const store = useWorkOnStore.getState();
  store.set("other", target);
  store.applyProject("cloud-project", null);
  store.adopt("project-chat");
  expect(store.targetFor("project-chat")).toBeNull();
  store.set("third", { ...target, folder: "/third" });
  expect(store.targetFor("project-chat")).toBeNull();
});
