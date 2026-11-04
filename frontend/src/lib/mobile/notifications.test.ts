import { beforeEach, expect, it, vi } from "vitest";
import {
  readMobilePushPreferences,
  saveMobilePushPreferences,
  setPushFocus,
} from "./notifications";
const env = vi.hoisted(() => ({ user: {} as object, get: vi.fn(), put: vi.fn(), invoke: vi.fn() }));
vi.mock("@/stores", () => ({ useAuthStore: { getState: () => ({ user: env.user }) } }));
vi.mock("@/lib/api-client", () => ({ apiClient: { get: env.get, put: env.put } }));
vi.mock("@/lib/desktop/shell", () => ({ invokeShell: env.invoke }));
beforeEach(() => {
  vi.clearAllMocks();
  env.user = {};
});
it("binds native notification taps to the authenticated sign-in returned by the server", async () => {
  const data = { hide_previews: true, muted_conversations: [], session_id: "session" };
  env.get.mockResolvedValue(data);
  expect(await readMobilePushPreferences()).toEqual(data);
  expect(env.invoke).toHaveBeenCalledWith("bind_push_session", { sessionId: "session" });
});
it("discards an old account's response before it changes native notification ownership", async () => {
  env.get.mockImplementation(async () => {
    env.user = {};
    return { session_id: "old" };
  });
  await expect(readMobilePushPreferences()).rejects.toMatchObject({ name: "AbortError" });
  expect(env.invoke).not.toHaveBeenCalled();
});
it("saves privacy and focus through separate requests so a heartbeat cannot reset preferences", async () => {
  const prefs = { hide_previews: true, muted_conversations: ["conversation"] };
  await saveMobilePushPreferences(prefs);
  await setPushFocus(null);
  expect(env.put).toHaveBeenCalledWith("/push/preferences", prefs);
  expect(env.put).toHaveBeenCalledWith("/push/focus", { conversation_id: null });
});
