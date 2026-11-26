import { expect, it, vi } from "vitest";
import { readAccountPreferences, saveAccountAppearance } from "./account-preferences-api";
const api = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn() }));
vi.mock("./api-client", () => ({ apiClient: api }));
it("reads and patches only self preferences", async () => {
  const saved = { theme: "system", look: "glass", locale: "en" };
  api.get.mockResolvedValue(saved);
  api.patch.mockResolvedValue(saved);
  expect(await readAccountPreferences()).toEqual(saved);
  expect(api.get).toHaveBeenCalledWith("/users/me/preferences");
  expect(await saveAccountAppearance({ look: "glass" })).toEqual(saved);
  expect(api.patch).toHaveBeenCalledWith("/users/me/preferences", { look: "glass" });
});
