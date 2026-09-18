import { beforeEach, describe, expect, it, vi } from "vitest";

import { acceptStagedInvitation, stageInvitation } from "./invitation-staging";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({ apiClient: { post: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

describe("staging an invitation from the browser", () => {
  it("posts the token and answers the flow the staging was bound to", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      staged: true,
      flow: "0123456789abcdef0123456789abcdef",
    });

    await expect(stageInvitation("a-token")).resolves.toBe("0123456789abcdef0123456789abcdef");
    expect(apiClient.post).toHaveBeenCalledWith("/invitations/stage", { token: "a-token" });
  });

  it("answers nothing for a refused staging rather than throwing", async () => {
    // A forged token, a rate limit and an unreachable server all land here; the
    // caller keeps the invitee on the link they hold and offers to try again.
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("not found"));

    await expect(stageInvitation("forged")).resolves.toBeNull();
  });
});

describe("accepting a staged invitation", () => {
  it("posts to the pending accept naming the flow, which reads that cookie server-side", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(undefined);

    await acceptStagedInvitation("0123456789abcdef0123456789abcdef");

    expect(apiClient.post).toHaveBeenCalledWith(
      "/invitations/pending/accept?flow=0123456789abcdef0123456789abcdef",
    );
  });

  it("still asks with no flow, and lets the miss surface", async () => {
    // A landing opened without its flow has nothing to redeem; the route answers a
    // miss and the card reports it as a refused invitation.
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("not found"));

    await expect(acceptStagedInvitation(null)).rejects.toThrow("not found");
    expect(apiClient.post).toHaveBeenCalledWith("/invitations/pending/accept");
  });

  it("lets a refusal surface rather than swallowing it", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("expired"));

    await expect(acceptStagedInvitation("0123456789abcdef0123456789abcdef")).rejects.toThrow(
      "expired",
    );
  });
});
