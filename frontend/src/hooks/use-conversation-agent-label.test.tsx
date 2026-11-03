import { renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useConversationAgentLabel } from "./use-conversation-agent-label";
import type { ConversationAgent } from "@/types/conversation";

const agent: ConversationAgent = {
  id: "a",
  slug: "assistant",
  name: "AgenticOS",
  has_avatar: false,
};
it("has no label without participants, and names a sole platform agent or harness", () => {
  expect(renderHook(() => useConversationAgentLabel([], [])).result.current).toBeNull();
  expect(renderHook(() => useConversationAgentLabel([agent], [])).result.current).toBe("AgenticOS");
  expect(renderHook(() => useConversationAgentLabel([], ["codex"])).result.current).toBe("Codex");
});
it("counts platform agents separately from the coding workers", () => {
  expect(
    renderHook(() =>
      useConversationAgentLabel([agent, { ...agent, id: "b" }], ["claude_code", "codex"]),
    ).result.current,
  ).toBe("2 agents · Claude Code · Codex");
});
