import { describe, expect, it, vi } from "vitest";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("./api-client", () => ({ apiClient: { get, post } }));

import { acceptSuggestion, dismissSuggestion, listSuggestions } from "./suggestions-api";

describe("the suggestions API", () => {
  it("lists the open ones and answers each by its id", async () => {
    get.mockResolvedValue({ items: [{ id: "s1" }], total: 1 });
    post.mockResolvedValue({ id: "s1" });

    expect(await listSuggestions()).toEqual([{ id: "s1" }]);
    await acceptSuggestion("s1");
    await dismissSuggestion("s2");

    expect(get).toHaveBeenCalledWith("/me/suggestions");
    expect(post.mock.calls.map(([path]) => path)).toEqual([
      "/me/suggestions/s1/accept",
      "/me/suggestions/s2/dismiss",
    ]);
  });
});
