import { describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn());
vi.mock("./api-client", () => ({ apiClient: { post } }));

import { askForCapability, enableCapability } from "./capability-requests-api";

describe("the capability card's two answers", () => {
  it("switches the capability on and says whether it is live", async () => {
    post.mockResolvedValue({ published: true });

    await expect(enableCapability("a-1", "web_search")).resolves.toEqual({ published: true });
    expect(post).toHaveBeenCalledWith("/agents/a-1/capabilities/web_search/enable");
  });

  it("asks the owner with the agent's own reason, the id escaped into the path", async () => {
    post.mockResolvedValue(undefined);

    await askForCapability("a-1", "a/b", "to read the page");

    expect(post).toHaveBeenCalledWith("/agents/a-1/capabilities/a%2Fb/request", {
      reason: "to read the page",
    });
  });
});
