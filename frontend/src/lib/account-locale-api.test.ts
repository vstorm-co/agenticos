import { describe, expect, it, vi } from "vitest";

const put = vi.hoisted(() => vi.fn());
vi.mock("./api-client", () => ({ apiClient: { put } }));

import { saveAccountLocale } from "./account-locale-api";

describe("saveAccountLocale", () => {
  it("keeps the choice on the account and answers with what was saved", async () => {
    put.mockResolvedValue({ locale: "en" });

    await expect(saveAccountLocale("en")).resolves.toBe("en");
    expect(put).toHaveBeenCalledWith("/users/me/locale", { locale: "en" });
  });
});
