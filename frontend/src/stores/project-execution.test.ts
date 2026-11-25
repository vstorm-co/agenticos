import { beforeEach, expect, it } from "vitest";
import { useWorkOnStore } from "./work-on-store";
import { useAuthStore } from "./auth-store";
import { useOrgStore } from "./org-store";

beforeEach(() => {
  useWorkOnStore.setState({
    executionByConversation: {},
    draftExecutionByScope: {},
    byConversation: {},
  });
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: "org-a" });
});
it("starts with the server default and keeps a project-specific draft for only its owner and tenant", () => {
  const store = useWorkOnStore.getState();
  expect(store.executionFor(null, "a")).toBeNull();
  store.setExecution(null, "a", "agent");
  expect(store.executionFor(null, "a")).toBe("agent");
  expect(store.executionFor(null, "b")).toBeNull();
  useOrgStore.setState({ activeOrgId: "org-b" });
  expect(store.executionFor(null, "a")).toBeNull();
  useOrgStore.setState({ activeOrgId: "org-a" });
  expect(store.executionFor(null, "a")).toBe("agent");
  store.resetDraft();
  expect(store.executionFor(null, "a")).toBeNull();
});
it("adopts an explicit choice for the created chat without inheriting it into a new chat", () => {
  const store = useWorkOnStore.getState();
  store.setExecution(null, "project", "project");
  store.adopt("chat");
  expect(store.executionFor("chat")).toBe("project");
  expect(store.executionFor(null, "project")).toBeNull();
  store.setExecution("chat", "project", "agent");
  expect(store.executionFor("chat")).toBe("agent");
  useOrgStore.setState({ activeOrgId: "org-b" });
  expect(store.executionFor("chat")).toBeNull();
});
