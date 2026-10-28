import { beforeEach, expect, it, vi } from "vitest";
import {
  parseReadiness,
  readDesktopReadiness,
  readDesktopFocus,
  requestDesktopPermission,
} from "./readiness";
const invoke = vi.hoisted(() => vi.fn());
vi.mock("./shell", async (original) => ({
  ...(await original<typeof import("./shell")>()),
  invokeShell: invoke,
}));
beforeEach(() => invoke.mockReset());
const status = {
  connection_revision: "r1",
  screen_capture: "granted",
  accessibility: "denied",
  microphone: "not_determined",
  notifications: "unsupported",
};
it("validates every native status and keeps unsupported separate from denied", async () => {
  expect(parseReadiness(status)).toEqual(status);
  for (const value of [
    null,
    {},
    { ...status, notifications: true },
    { ...status, microphone: "allowed" },
  ])
    expect(() => parseReadiness(value)).toThrow("malformed");
  invoke.mockResolvedValue(status);
  expect(await readDesktopReadiness()).toEqual(status);
  expect(invoke).toHaveBeenLastCalledWith("desktop_readiness");
});
it("only requests the explicitly selected permission and validates focus context", async () => {
  await requestDesktopPermission("microphone");
  expect(invoke).toHaveBeenLastCalledWith("desktop_request_permission", {
    permission: "microphone",
  });
  invoke.mockResolvedValue({ focused: true, conversation_id: "chat" });
  expect(await readDesktopFocus()).toEqual({ focused: true, conversation_id: "chat" });
  invoke.mockResolvedValue({ focused: true });
  await expect(readDesktopFocus()).rejects.toThrow("malformed");
});
