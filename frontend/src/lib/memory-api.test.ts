import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  correctClaim,
  deleteNote,
  getMyClaims,
  getMyMemory,
  getPersonMemory,
  retractClaim,
  setNoteActive,
} from "./memory-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn(), delete: vi.fn(), post: vi.fn() },
}));

const PAGE = { items: [], total: 0 };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue(PAGE);
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "n-1" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("the claims API", () => {
  it("reads the live claims, or the history too", async () => {
    await getMyClaims(false);
    await getMyClaims(true);

    expect(apiClient.get).toHaveBeenCalledWith("/memory/claims/mine?limit=100&history=false");
    expect(apiClient.get).toHaveBeenCalledWith("/memory/claims/mine?limit=100&history=true");
  });

  it("posts a correction with its effective date, and a retraction with nothing", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "c-1" });

    await correctClaim("c-1", "New", "2026-11-03T00:00:00Z");
    await retractClaim("c-1");

    expect(apiClient.post).toHaveBeenCalledWith("/memory/claims/mine/c-1/correct", {
      statement: "New",
      effective_from: "2026-11-03T00:00:00Z",
    });
    expect(apiClient.post).toHaveBeenCalledWith("/memory/claims/mine/c-1/retract", {});
  });
});

describe("the memory API", () => {
  it("reads the caller's own store with the window they asked for", async () => {
    await expect(getMyMemory(40, 20)).resolves.toEqual(PAGE);
    expect(apiClient.get).toHaveBeenCalledWith("/memory/mine?skip=40&limit=20");
  });

  it("suppresses a note by saying it is not active", async () => {
    await setNoteActive("n-1", false);

    expect(apiClient.patch).toHaveBeenCalledWith("/memory/mine/n-1", { active: false });
  });

  it("deletes one note by id", async () => {
    await deleteNote("n-1");

    expect(apiClient.delete).toHaveBeenCalledWith("/memory/mine/n-1");
  });

  it("names the tenant and the reason when reading somebody else's", async () => {
    // The tenant is explicit because an app admin acts across tenants, and a read
    // that silently used whichever one they had selected is one nobody can audit.
    await getPersonMemory("u-1", "o-1", "DSAR 41");

    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/person/u-1?organization_id=o-1&skip=0&limit=50&reason=DSAR+41",
    );
  });

  it("omits the reason where none was given", async () => {
    await getPersonMemory("u-1", "o-1");

    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/person/u-1?organization_id=o-1&skip=0&limit=50",
    );
  });

  it("carries a window, so an inspection can reach past the first page", async () => {
    // An inspection that could only ever see the first fifty notes of a larger
    // store cannot answer a subject-access request.
    await getPersonMemory("u-1", "o-1", undefined, 50, 25);

    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/person/u-1?organization_id=o-1&skip=50&limit=25",
    );
  });
});
