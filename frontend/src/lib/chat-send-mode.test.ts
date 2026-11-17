import { describe, expect, it } from "vitest";

import { chatSendModeScope, isChatSendMode, isChatSendModeScope } from "./chat-send-mode";

describe("chat send mode", () => {
  it("requires an account, organization and agent before storing a preference", () => {
    expect(chatSendModeScope("account-1", "org-1", "agent-1")).toBe(
      '["account-1","org-1","agent-1"]',
    );
    expect(chatSendModeScope("account-1", "org-1", null)).toBe('["account-1","org-1",null]');
    expect(chatSendModeScope(null, "org-1", "agent-1")).toBeNull();
    expect(chatSendModeScope("account-1", null, "agent-1")).toBeNull();
    expect(chatSendModeScope("account-1", "org-1", " ")).toBeNull();
    expect(chatSendModeScope("account-1", "org-1", undefined)).toBeNull();
  });

  it("validates stored modes and scope keys", () => {
    expect(isChatSendMode("queue")).toBe(true);
    expect(isChatSendMode("steer")).toBe(true);
    expect(isChatSendMode("send-now")).toBe(false);
    expect(isChatSendModeScope('["account-1","org-1","agent-1"]')).toBe(true);
    expect(isChatSendModeScope('["account-1","org-1",null]')).toBe(true);
    expect(isChatSendModeScope('["account-1","org-1"]')).toBe(false);
    expect(isChatSendModeScope('["account-1",null,"agent-1"]')).toBe(false);
    expect(isChatSendModeScope("not-json")).toBe(false);
  });
});
