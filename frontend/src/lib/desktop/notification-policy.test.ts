import { expect, it } from "vitest";
import { DEFAULT_DESKTOP_NOTIFICATIONS } from "@/stores/desktop-preferences-store";
import { notificationConversation, shouldNotify } from "./notification-policy";
const input = {
  event: "run_completed",
  path: "/chat?id=one",
  preferences: DEFAULT_DESKTOP_NOTIFICATIONS,
  activeConversation: "one",
  focused: false,
};
it("suppresses a viewed conversation only while its native window is focused", () => {
  expect(shouldNotify(input)).toBe(true);
  expect(shouldNotify({ ...input, focused: true })).toBe(false);
  expect(shouldNotify({ ...input, focused: true, activeConversation: "two" })).toBe(true);
  expect(shouldNotify({ ...input, focused: true, path: "/inbox" })).toBe(true);
});
it.each([
  ["run_completed", "completed"],
  ["run_failed", "failed"],
  ["approval_requested", "approvals"],
  ["background_task_paused", "questions"],
  ["resource_shared", "other"],
] as const)("honours the %s event preference", (event, setting) => {
  expect(
    shouldNotify({ ...input, event, preferences: { ...input.preferences, [setting]: false } }),
  ).toBe(false);
});
it("muting one conversation does not mute others or the inbox", () => {
  const preferences = { ...input.preferences, muted_conversations: ["one"] };
  expect(shouldNotify({ ...input, preferences })).toBe(false);
  expect(shouldNotify({ ...input, preferences, path: "/chat?id=two" })).toBe(true);
  expect(notificationConversation("/pl/chat?id=one")).toBe("one");
  expect(notificationConversation(null)).toBeNull();
  expect(notificationConversation("http://[")).toBeNull();
});
