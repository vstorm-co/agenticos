import { beforeEach, describe, expect, it, vi } from "vitest";

import { acceptStagedInvitation, stageInvitation } from "./invitation-staging";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({ apiClient: { post: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

describe("staging an invitation from the browser", () => {
  it("posts the token and reports a live invitation", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(undefined);

    await expect(stageInvitation("a-token")).resolves.toBe(true);
    expect(apiClient.post).toHaveBeenCalledWith("/invitations/stage", { token: "a-token" });
  });

  it("reports a refused token rather than throwing", async () => {
    // A forged or expired token answers a refusal; the caller sends the invitee on
    // to sign in either way, and the pending page reports the invalid one.
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("not found"));

    await expect(stageInvitation("forged")).resolves.toBe(false);
  });
});

describe("accepting a staged invitation", () => {
  it("posts to the pending accept, which reads the cookie server-side", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(undefined);

    await acceptStagedInvitation();

    expect(apiClient.post).toHaveBeenCalledWith("/invitations/pending/accept");
  });

  it("lets a refusal surface rather than swallowing it", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("expired"));

    await expect(acceptStagedInvitation()).rejects.toThrow("expired");
  });
});
