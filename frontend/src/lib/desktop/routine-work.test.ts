import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  allowRoutine,
  coveredByAllRoutines,
  chooseRoutineFolder,
  listRoutineGrants,
  revokeRoutineGrant,
} from "./routine-work";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("./shell")>()),
  invokeShell: invoke,
}));
const org = "00000000-0000-4000-8000-000000000001";
const user = "00000000-0000-4000-8000-000000000002";
const device = "00000000-0000-4000-8000-000000000003";
const routine = "00000000-0000-4000-8000-000000000004";
const id = "00000000-0000-4000-8000-000000000005";
const operations = { read: true as const, write: false, execute: false };
const request = {
  organization_id: org,
  user_id: user,
  device_id: device,
  routine_id: routine,
  name: "Report",
  root: "/work",
  operations,
};
const grant = {
  id,
  organization_id: org,
  routine_id: routine,
  name: "Report",
  root: "/work",
  identity: { origin: "https://example.com", user_id: user, device_id: device },
  operations,
};
beforeEach(() => invoke.mockReset());
describe("routine native boundary", () => {
  it("chooses a preview without granting general folder access", async () => {
    invoke.mockResolvedValue("/work");
    expect(await chooseRoutineFolder()).toBe("/work");
    expect(invoke).toHaveBeenCalledExactlyOnceWith("routine_choose_folder");
  });
  it("preserves cancellation without fabricating consent", async () => {
    invoke.mockResolvedValue(null);
    expect(await allowRoutine(request)).toBeNull();
  });
  it("returns an exact routine target rather than a general folder grant", async () => {
    invoke.mockResolvedValue(grant);
    expect(await allowRoutine(request)).toEqual({
      folder: "/work",
      mode: "read_only",
      device_id: device,
      routine_grant: id,
      operations,
    });
    expect(invoke).toHaveBeenCalledWith("routine_allow", { request });
  });
  it.each([
    { organization_id: routine },
    { routine_id: org },
    { root: "/elsewhere" },
    { identity: { ...grant.identity, user_id: org } },
    { identity: { ...grant.identity, device_id: org } },
    { operations: { ...operations, write: true } },
    { operations: { ...operations, execute: true } },
  ])("refuses a changed permission binding %j", async (change) => {
    invoke.mockResolvedValue({ ...grant, ...change });
    await expect(allowRoutine(request)).rejects.toThrow("malformed");
  });
  it("rejects command access without write before IPC", async () => {
    await expect(
      allowRoutine({ ...request, operations: { ...operations, execute: true } }),
    ).rejects.toThrow();
    expect(invoke).not.toHaveBeenCalled();
  });
  it("checks the owner and organization when listing grants", async () => {
    invoke.mockResolvedValue([grant]);
    expect(await listRoutineGrants(org, user)).toEqual([grant]);
    await expect(listRoutineGrants(routine, user)).rejects.toThrow("malformed");
    await expect(listRoutineGrants(org, org)).rejects.toThrow("malformed");
  });
  it("revokes only the scoped owner grant", async () => {
    invoke.mockResolvedValue(undefined);
    await revokeRoutineGrant(id, org, user);
    expect(invoke).toHaveBeenCalledExactlyOnceWith("routine_revoke", {
      id,
      organizationId: org,
      userId: user,
    });
  });
});

it("refuses additional command authority even when write access matches", async () => {
  invoke.mockResolvedValue({ ...grant, operations: { read: true, write: true, execute: true } });
  await expect(
    allowRoutine({ ...request, operations: { read: true, write: true, execute: false } }),
  ).rejects.toThrow("malformed");
});

it("keeps explicitly requested command access within the granted workspace mode", async () => {
  const operations = { read: true as const, write: true, execute: true };
  invoke.mockResolvedValue({ ...grant, operations });
  expect(await allowRoutine({ ...request, operations })).toMatchObject({
    mode: "workspace_write",
    operations,
  });
});

describe("coveredByAllRoutines", () => {
  const all = {
    id: "00000000-0000-4000-8000-000000000001",
    identity: { origin: "https://example.com", user_id: "u", device_id: "old-session" },
    organization_id: "o",
    routine_id: null,
    name: "All my routines",
    root: "/Users/person",
    operations: { read: true as const, write: true, execute: false },
  };
  const read = { read: true as const, write: false, execute: false };

  it("reuses it for a folder inside, on the session signed in now", () => {
    expect(coveredByAllRoutines([all], "now", "/Users/person/notes", read)).toEqual({
      device_id: "now",
      folder: "/Users/person/notes",
      mode: "read_only",
      routine_grant: all.id,
      operations: read,
    });
  });

  it.each([
    ["a sibling with the same prefix", "/Users/personal", read],
    ["a folder outside", "/tmp", read],
    [
      "commands it was not given",
      "/Users/person",
      { read: true as const, write: true, execute: true },
    ],
  ])("does not cover %s", (_case, folder, operations) => {
    expect(coveredByAllRoutines([all], "now", folder, operations)).toBeNull();
  });

  it("ignores a grant for one routine", () => {
    expect(
      coveredByAllRoutines([{ ...all, routine_id: "r" }], "now", "/Users/person", read),
    ).toBeNull();
  });

  it("reuses a grant for a Windows subfolder without replacing its ID", () => {
    expect(
      coveredByAllRoutines([{ ...all, root: "C:\\work" }], "now", "C:\\work\\reports", read),
    ).toMatchObject({
      device_id: "now",
      folder: "C:\\work\\reports",
      routine_grant: all.id,
    });
    expect(
      coveredByAllRoutines([{ ...all, root: "C:\\work" }], "now", "C:\\workshop", read),
    ).toBeNull();
  });

  it("treats the root folder as the whole computer", () => {
    expect(coveredByAllRoutines([{ ...all, root: "/" }], "now", "/srv/data", read)?.folder).toBe(
      "/srv/data",
    );
  });
});
