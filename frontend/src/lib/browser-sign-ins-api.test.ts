import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "./api-client";
import { forgetSignIn, getMySignIns } from "./browser-sign-ins-api";

vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), delete: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

describe("the browser sign-ins client", () => {
  it("reads the caller's own and forgets one by id", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });

    await getMySignIns();
    await forgetSignIn("s1");

    expect(apiClient.get).toHaveBeenCalledWith("/browser-sign-ins");
    expect(apiClient.delete).toHaveBeenCalledWith("/browser-sign-ins/s1");
  });
});
