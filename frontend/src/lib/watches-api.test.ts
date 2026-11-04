import { describe, expect, it, vi } from "vitest";

const client = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("./api-client", () => ({ apiClient: client }));

import {
  createWatch,
  deleteWatch,
  listWatchPresets,
  listWatches,
  updateWatch,
} from "./watches-api";

describe("the watches API", () => {
  it("lists the person's watches and the presets, and writes each by its id", async () => {
    client.get.mockImplementation(async (path: string) => ({
      items: [{ id: path.endsWith("presets") ? "github-reviews" : "w1" }],
      total: 1,
    }));
    client.post.mockResolvedValue({ id: "w2" });
    client.patch.mockResolvedValue({ id: "w2" });
    client.delete.mockResolvedValue(undefined);

    expect(await listWatches()).toEqual([{ id: "w1" }]);
    expect(await listWatchPresets()).toEqual([{ id: "github-reviews" }]);
    const draft = {
      connection_id: "c1",
      preset_key: null,
      title: "Reviews",
      instructions: "Waiting on me",
      urgent: false,
      interval_minutes: 60,
    };
    await createWatch(draft);
    await updateWatch("w2", { is_active: false });
    await deleteWatch("w2");

    expect(client.post).toHaveBeenCalledWith("/me/watches", draft);
    expect(client.patch).toHaveBeenCalledWith("/me/watches/w2", { is_active: false });
    expect(client.delete).toHaveBeenCalledWith("/me/watches/w2");
  });
});
