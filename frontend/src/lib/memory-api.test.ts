import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  amendHistoricalClaim,
  correctClaim,
  getMemoryClaimDetail,
  getMemoryObjects,
  getMemoryTimeline,
  getSharedClaims,
  getSharedNotes,
  resolveSharedMemoryConflict,
  reviewDecisionCase,
  shareMemoryClaim,
  shareMemoryNote,
  type MemoryNote,
  deleteNote,
  editNoteContent,
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
    await getMyClaims(true, 100);

    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/claims/mine?limit=100&skip=0&history=false",
    );
    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/claims/mine?limit=100&skip=100&history=true",
    );
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

it("encodes whole-store searches and narrows claims before pagination", async () => {
  await getMyClaims(false, 100, { q: "50% & invoices", kind: "decision", scope: "agent" });
  expect(apiClient.get).toHaveBeenCalledWith(
    "/memory/claims/mine?limit=100&skip=100&history=false&q=50%25+%26+invoices&kind=decision&scope=agent",
  );
  await getMyMemory(50, 50, "50% & invoices");
  expect(apiClient.get).toHaveBeenCalledWith(
    "/memory/mine?skip=50&limit=50&q=50%25%20%26%20invoices",
  );
});

it("partitions object browsing and passes both historical cutoffs and cursors", () => {
  void getMemoryObjects("personal", "", "all", null);
  void getMemoryObjects("organization", "Atlas & Co", "company", "page-b");
  void getMemoryTimeline("organization", "project", "", "2026-11-26", null);
  void getMemoryTimeline("organization", "project", "2020-01-01", "2026-11-26", "page-b");
  void getMemoryClaimDetail("organization", "c-1");
  expect(apiClient.get).toHaveBeenNthCalledWith(1, "/memory/objects?library=personal&q=");
  expect(apiClient.get).toHaveBeenNthCalledWith(
    2,
    "/memory/objects?library=organization&q=Atlas+%26+Co&kind=company&cursor=page-b",
  );
  expect(apiClient.get).toHaveBeenNthCalledWith(3, "/memory/objects/project?library=organization");
  expect(apiClient.get).toHaveBeenNthCalledWith(
    4,
    "/memory/objects/project?library=organization&as_of=2020-01-01T00%3A00%3A00Z&known_at=2026-11-26T23%3A59%3A59.999999Z&cursor=page-b",
  );
  expect(apiClient.get).toHaveBeenNthCalledWith(5, "/memory/claims/shared/c-1");
});

it("reads shared pages and sends only explicitly reviewed publication and decision fields", () => {
  const note: MemoryNote = {
    id: "n-1",
    agent_id: "a",
    agent_name: null,
    name: "notes.md",
    content: "private",
    description: null,
    format: "markdown",
    kind: "note",
    created_at: null,
    updated_at: "2026-11-26T00:00:00Z",
    written_at: null,
    deactivated_at: null,
  };
  void getSharedClaims("", 0);
  void getSharedClaims("Deadline", 30, true);
  void getSharedNotes(null);
  void getSharedNotes("page-b");
  void shareMemoryClaim("c-1", "group-1");
  void shareMemoryNote(note, null);
  void editNoteContent(note, "Edited note");
  void resolveSharedMemoryConflict("c-1", ["c-1", "c-2"]);
  void amendHistoricalClaim("c-1", "Revised");
  void reviewDecisionCase("c-1", "dataset-1", "Question", "Answer");
  expect(apiClient.get).toHaveBeenNthCalledWith(1, "/memory/claims/shared?q=&skip=0");
  expect(apiClient.get).toHaveBeenNthCalledWith(
    2,
    "/memory/claims/shared?q=Deadline&skip=30&disputed=true",
  );
  expect(apiClient.get).toHaveBeenNthCalledWith(3, "/memory/notes/shared?");
  expect(apiClient.get).toHaveBeenNthCalledWith(4, "/memory/notes/shared?cursor=page-b");
  expect(apiClient.post).toHaveBeenNthCalledWith(1, "/memory/claims/mine/c-1/share", {
    confirmed: true,
    group_id: "group-1",
  });
  expect(apiClient.post).toHaveBeenNthCalledWith(2, "/memory/mine/n-1/share", {
    confirmed: true,
    group_id: null,
    expected_updated_at: note.updated_at,
  });
  expect(apiClient.post).toHaveBeenNthCalledWith(3, "/memory/claims/shared/c-1/resolve", {
    candidate_ids: ["c-1", "c-2"],
  });
  expect(apiClient.post).toHaveBeenNthCalledWith(4, "/memory/claims/mine/c-1/correct", {
    statement: "Revised",
    historical: true,
  });
  expect(apiClient.patch).toHaveBeenCalledWith("/memory/mine/n-1/content", {
    content: "Edited note",
    expected_updated_at: note.updated_at,
  });
  expect(apiClient.post).toHaveBeenNthCalledWith(5, "/memory/claims/mine/c-1/improve-case", {
    confirmed: true,
    dataset_id: "dataset-1",
    input: "Question",
    reference_answer: "Answer",
  });
});
