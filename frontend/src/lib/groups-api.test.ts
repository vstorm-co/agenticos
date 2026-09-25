import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  addGroupMember,
  createGroup,
  deleteGroup,
  listGroupMembers,
  listGroups,
  removeGroupMember,
  updateGroup,
} from "./groups-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const GROUP = {
  id: "g-1",
  organization_id: "o-1",
  name: "Finance",
  description: null,
  member_count: 2,
  created_at: "2026-09-01T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("the groups API", () => {
  it("lists one organization's groups by its id, not the active one", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [GROUP], total: 1 });

    await expect(listGroups("o-1")).resolves.toEqual({ items: [GROUP], total: 1 });
    expect(apiClient.get).toHaveBeenCalledWith("/orgs/o-1/groups");
  });

  it("creates, renames and deletes a group at its own path", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(GROUP);
    vi.mocked(apiClient.patch).mockResolvedValue(GROUP);

    await expect(createGroup("o-1", { name: "Finance", description: null })).resolves.toBe(GROUP);
    await expect(updateGroup("o-1", "g-1", { description: null })).resolves.toBe(GROUP);
    await expect(deleteGroup("o-1", "g-1")).resolves.toBeUndefined();

    expect(apiClient.post).toHaveBeenCalledWith("/orgs/o-1/groups", {
      name: "Finance",
      description: null,
    });
    // `null` is sent, not dropped: it is how a description is cleared.
    expect(apiClient.patch).toHaveBeenCalledWith("/orgs/o-1/groups/g-1", { description: null });
    expect(apiClient.delete).toHaveBeenCalledWith("/orgs/o-1/groups/g-1");
  });

  it("reads and changes one group's members", async () => {
    const row = {
      user_id: "u-1",
      email: "a@acme.test",
      full_name: null,
      source: "manual",
      created_at: "2026-09-01T00:00:00Z",
    };
    vi.mocked(apiClient.get).mockResolvedValue({ items: [row], total: 1 });
    vi.mocked(apiClient.post).mockResolvedValue(row);

    await expect(listGroupMembers("o-1", "g-1")).resolves.toEqual({ items: [row], total: 1 });
    await expect(addGroupMember("o-1", "g-1", "u-1")).resolves.toBe(row);
    await expect(removeGroupMember("o-1", "g-1", "u-1")).resolves.toBeUndefined();

    expect(apiClient.get).toHaveBeenCalledWith("/orgs/o-1/groups/g-1/members");
    expect(apiClient.post).toHaveBeenCalledWith("/orgs/o-1/groups/g-1/members", {
      user_id: "u-1",
    });
    expect(apiClient.delete).toHaveBeenCalledWith("/orgs/o-1/groups/g-1/members/u-1");
  });
});
