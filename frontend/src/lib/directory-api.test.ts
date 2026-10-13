import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createDirectoryMapping,
  deleteDirectoryMapping,
  listDirectoryMappings,
} from "./directory-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const MAPPING = {
  id: "m-1",
  organization_id: "o-1",
  external_group: "cn=finance,ou=groups,dc=acme,dc=test",
  role: "member",
  group_id: null,
  group_name: null,
  created_at: "2026-09-01T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("the directory mappings API", () => {
  it("lists one organization's mappings by its id", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [MAPPING], total: 1 });

    await expect(listDirectoryMappings("o-1")).resolves.toEqual({ items: [MAPPING], total: 1 });
    expect(apiClient.get).toHaveBeenCalledWith("/orgs/o-1/directory-mappings");
  });

  it("sends the external group, the role and the group - null when there is none", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(MAPPING);

    await createDirectoryMapping("o-1", {
      external_group: MAPPING.external_group,
      role: "member",
      group_id: null,
    });

    expect(apiClient.post).toHaveBeenCalledWith("/orgs/o-1/directory-mappings", {
      external_group: MAPPING.external_group,
      role: "member",
      group_id: null,
    });
  });

  it("deletes a mapping at its own path", async () => {
    await expect(deleteDirectoryMapping("o-1", "m-1")).resolves.toBeUndefined();
    expect(apiClient.delete).toHaveBeenCalledWith("/orgs/o-1/directory-mappings/m-1");
  });
});
