import { beforeEach, describe, expect, it, vi } from "vitest";

import { rateMessage, removeRating } from "./message-rating-api";
import { apiClient } from "./api-client";
import { RatingValue } from "@/types/chat";

vi.mock("./api-client", () => ({
  apiClient: { post: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.post).mockResolvedValue({});
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("the message rating API", () => {
  it("posts a rating to the message's rate endpoint through the shared client", async () => {
    await rateMessage("c-1", "m-1", { rating: RatingValue.LIKE, comment: null });

    expect(apiClient.post).toHaveBeenCalledWith("/conversations/c-1/messages/m-1/rate", {
      rating: RatingValue.LIKE,
      comment: null,
    });
  });

  it("encodes ids that are not path-safe", async () => {
    await rateMessage("c/1", "m 1", { rating: RatingValue.DISLIKE, comment: "x" });

    expect(apiClient.post).toHaveBeenCalledWith("/conversations/c%2F1/messages/m%201/rate", {
      rating: RatingValue.DISLIKE,
      comment: "x",
    });
  });

  it("removes a rating with a DELETE", async () => {
    await removeRating("c-1", "m-1");

    expect(apiClient.delete).toHaveBeenCalledWith("/conversations/c-1/messages/m-1/rate");
  });
});
