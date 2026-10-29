import { afterEach, expect, it, vi } from "vitest";
import { recallConversation, rememberConversation } from "./architect-conversation";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("remembers one conversation per person and organization, and forgets it on a new one", () => {
  rememberConversation("u1", "o1", "c1");
  rememberConversation("u1", "o2", "c2");
  expect(recallConversation("u1", "o1")).toBe("c1");
  expect(recallConversation("u2", "o1")).toBeNull();
  rememberConversation("u1", "o1", null);
  expect(recallConversation("u1", "o1")).toBeNull();
  expect(recallConversation("u1", "o2")).toBe("c2");
});

it("starts afresh rather than failing when the browser keeps nothing", () => {
  const blocked = () => {
    throw new Error("blocked");
  };
  vi.stubGlobal("localStorage", { getItem: blocked, setItem: blocked, removeItem: blocked });
  expect(() => rememberConversation("u1", "o1", "c1")).not.toThrow();
  expect(recallConversation("u1", "o1")).toBeNull();
});
