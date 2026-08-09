import { beforeEach, describe, expect, it, vi } from "vitest";

import { confirmChannelLink, readChannelLink } from "./channel-link-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

/**
 * Claiming a chat account for the signed-in person.
 *
 * The token arrives in a chat and the session says who is accepting, so the
 * confirmation is a POST from an authenticated browser and never anything the
 * bot can do by itself.
 */
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ platform: "mattermost" });
  vi.mocked(apiClient.post).mockResolvedValue({ platform: "mattermost" });
});

describe("the channel link API", () => {
  it("reads which account a URL is about", async () => {
    await expect(readChannelLink("tok")).resolves.toEqual({ platform: "mattermost" });
    expect(apiClient.get).toHaveBeenCalledWith("/me/channel-link/tok");
  });

  it("confirms with a POST rather than a read", async () => {
    await confirmChannelLink("tok");

    expect(apiClient.post).toHaveBeenCalledWith("/me/channel-link/tok", {});
  });

  it("escapes a token that would otherwise change the path", async () => {
    // The token is `secrets.token_urlsafe`, so `-` and `_` only - but it reaches
    // here from a URL somebody pasted, and a `/` in it would address a different
    // endpoint entirely.
    await readChannelLink("a/b?c");

    expect(apiClient.get).toHaveBeenCalledWith("/me/channel-link/a%2Fb%3Fc");
  });
});
