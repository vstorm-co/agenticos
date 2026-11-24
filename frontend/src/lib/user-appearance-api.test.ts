import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_APPEARANCE } from "@/lib/user-appearance";
import { getUserAppearance, resetUserAppearance, saveUserAppearance } from "./user-appearance-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => vi.resetAllMocks());

it("reads the session owner's appearance with the caller's cancellation signal", async () => {
  vi.mocked(apiClient.get).mockResolvedValue(DEFAULT_APPEARANCE);
  const signal = new AbortController().signal;
  await expect(getUserAppearance(signal)).resolves.toEqual(DEFAULT_APPEARANCE);
  expect(apiClient.get).toHaveBeenCalledWith("/users/me/appearance", { signal });
});

it("sends only edited fields and accepts the complete acknowledged appearance", async () => {
  const saved = { ...DEFAULT_APPEARANCE, theme: "dark", radius: "rounded" };
  vi.mocked(apiClient.patch).mockResolvedValue(saved);
  await expect(saveUserAppearance({ theme: "dark", radius: "rounded" })).resolves.toEqual(saved);
  expect(apiClient.patch).toHaveBeenCalledWith("/users/me/appearance", {
    theme: "dark",
    radius: "rounded",
  });
});

it("resets through DELETE and reads the returned account defaults", async () => {
  vi.mocked(apiClient.delete).mockResolvedValue(DEFAULT_APPEARANCE);
  await expect(resetUserAppearance()).resolves.toEqual(DEFAULT_APPEARANCE);
  expect(apiClient.delete).toHaveBeenCalledWith("/users/me/appearance");
});

it.each([
  ["read", () => getUserAppearance(), "get"],
  ["save", () => saveUserAppearance({ theme: "dark" }), "patch"],
  ["reset", () => resetUserAppearance(), "delete"],
] as const)(
  "rejects malformed %s responses before they reach the console",
  async (_name, call, verb) => {
    vi.mocked(apiClient[verb]).mockResolvedValue({ ...DEFAULT_APPEARANCE, accent: "url(evil)" });
    await expect(call()).rejects.toThrow();
  },
);

it("preserves a refused write as a failure", async () => {
  const refusal = new Error("session expired");
  vi.mocked(apiClient.patch).mockRejectedValue(refusal);
  await expect(saveUserAppearance({ look: "paper" })).rejects.toBe(refusal);
});
