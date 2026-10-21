import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "./api-client";
import { createPairingCode, pairingLink, redeemPairingCode } from "./pairing-api";

vi.mock("./api-client", () => ({ apiClient: { post: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

describe("pairing", () => {
  it("asks for a code and redeems one through the BFF", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ code: "c", expires_in: 60 });
    await expect(createPairingCode()).resolves.toEqual({ code: "c", expires_in: 60 });
    expect(apiClient.post).toHaveBeenCalledWith("/auth/pairing-codes");
    await redeemPairingCode("c");
    expect(apiClient.post).toHaveBeenLastCalledWith("/auth/pair", { code: "c" });
  });

  it("links the app to this console with the code, escaped", () => {
    expect(pairingLink("https://agenticos.acme.com", "a+b/c")).toBe(
      "agenticos://pair?server=https%3A%2F%2Fagenticos.acme.com&code=a%2Bb%2Fc",
    );
  });
});
