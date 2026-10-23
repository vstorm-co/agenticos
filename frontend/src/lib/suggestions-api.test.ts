import { describe, expect, it, vi } from "vitest";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("./api-client", () => ({ apiClient: { get, post } }));

import {
  acceptSuggestion,
  dismissSuggestion,
  listPersonalStarters,
  listSuggestionHistory,
  listSuggestions,
  restoreSuggestion,
} from "./suggestions-api";

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

describe("the suggestion history", () => {
  it("lists every one, answered or not, and restores one by its id", async () => {
    get.mockResolvedValue({ items: [{ id: "s3" }], total: 1 });
    post.mockResolvedValue({ id: "s3" });

    expect(await listSuggestionHistory()).toEqual([{ id: "s3" }]);
    await restoreSuggestion("s3");

    expect(get).toHaveBeenCalledWith("/me/suggestions?decided=true");
    expect(post).toHaveBeenCalledWith("/me/suggestions/s3/restore");
  });
});

describe("the first messages written for the person", () => {
  it("reads them for the active organization", async () => {
    get.mockResolvedValue({ items: ["Plan my week"] });

    expect(await listPersonalStarters()).toEqual(["Plan my week"]);
    expect(get).toHaveBeenCalledWith("/me/suggestions/starters");
  });
});
