import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearTeachingAttempt,
  readTeachingAttempt,
  retainTeachingAttempt,
  teachingAttemptKey,
  type TeachingAttempt,
  type TeachingDraftAttempt,
  type TeachingStartAttempt,
} from "./browser-teaching-attempts";
import { TEACHING_IDS as ids } from "@/test-utils/browser-teaching";

const audience = { actor: ids.owner, organization: ids.org };
const now = Date.parse("2030-01-01T00:00:00Z");
const retention = 86_400_000;
const start = (): TeachingStartAttempt => ({
  kind: "start",
  body: {
    request_id: ids.session,
    run_id: ids.run,
    call_id: "teaching-call",
    tab_id: "main",
    takeover_id: ids.takeover,
    title: "Monthly report demonstration",
    allowed_origins: ["https://reports.example"],
  },
  targetSkillId: null,
});
const draft = (): TeachingDraftAttempt => ({
  kind: "propose",
  revision: 2,
  body: { mode: "reviewed" },
});
const startKey = teachingAttemptKey(audience, "start", [ids.run, "teaching-call", "main"]);
const draftKey = teachingAttemptKey(audience, "propose", [ids.session]);
const blocked = { attempt: null, blocked: true };
const empty = { attempt: null, blocked: false };
const writeRecord = (attempt: unknown, key = startKey, createdAt = now) =>
  sessionStorage.setItem(key, JSON.stringify({ createdAt, attempt }));

beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("scoped teaching attempt retention", () => {
  it("has distinct owner, organization, action and live-view keys", () => {
    const keys = [
      startKey,
      draftKey,
      teachingAttemptKey({ ...audience, actor: ids.other }, "start", [
        ids.run,
        "teaching-call",
        "main",
      ]),
      teachingAttemptKey({ ...audience, organization: ids.other }, "start", [
        ids.run,
        "teaching-call",
        "main",
      ]),
      teachingAttemptKey(audience, "start", [ids.other, "teaching-call", "main"]),
      teachingAttemptKey(audience, "start", [ids.run, "other-call", "main"]),
      teachingAttemptKey(audience, "start", [ids.run, "teaching-call", "other-tab"]),
    ];
    expect(new Set(keys).size).toBe(keys.length);
    expect(readTeachingAttempt(startKey, "start", now)).toEqual(empty);
    expect(
      readTeachingAttempt(
        teachingAttemptKey({ actor: undefined, organization: null }, "start", []),
        "start",
        now,
      ),
    ).toEqual(empty);
  });

  it.each([null, ids.skill])(
    "preserves the exact Start body and target %s across a new read",
    (targetSkillId) => {
      const attempt = { ...start(), targetSkillId };
      expect(retainTeachingAttempt(startKey, attempt, now)).toBe(true);
      expect(readTeachingAttempt<TeachingStartAttempt>(startKey, "start", now + 1)).toEqual({
        attempt,
        blocked: false,
      });
      expect(
        readTeachingAttempt<TeachingStartAttempt>(startKey, "start", now + 1).attempt,
      ).not.toBe(attempt);
      expect(readTeachingAttempt(draftKey, "propose", now)).toEqual(empty);
    },
  );

  it.each([
    { mode: "reviewed" } as const,
    { mode: "assistant", max_cost_usd: "0.123456" } as const,
  ])("retains the exact revision and $mode consent", (body) => {
    const attempt: TeachingDraftAttempt = { ...draft(), body };
    expect(retainTeachingAttempt(draftKey, attempt, now)).toBe(true);
    expect(readTeachingAttempt(draftKey, "propose", now + 1)).toEqual({ attempt, blocked: false });
    const raw = sessionStorage.getItem(draftKey);
    expect(retainTeachingAttempt(draftKey, structuredClone(attempt), now + 100)).toBe(true);
    expect(sessionStorage.getItem(draftKey)).toBe(raw);
  });

  it("does not replace an unresolved Start or renew its retention on identical explicit retry", () => {
    const attempt = start();
    expect(retainTeachingAttempt(startKey, attempt, now)).toBe(true);
    const raw = sessionStorage.getItem(startKey);
    const writer = vi.spyOn(sessionStorage, "setItem");
    expect(
      retainTeachingAttempt(
        startKey,
        {
          targetSkillId: null,
          body: { ...attempt.body },
          kind: "start",
        },
        now + retention - 1,
      ),
    ).toBe(true);
    expect(writer).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(startKey)).toBe(raw);
    for (const changed of [
      { ...attempt, body: { ...attempt.body, request_id: ids.other } },
      { ...attempt, body: { ...attempt.body, takeover_id: ids.other } },
      { ...attempt, body: { ...attempt.body, title: "Different review" } },
      { ...attempt, body: { ...attempt.body, allowed_origins: ["https://second.example"] } },
      { ...attempt, targetSkillId: ids.skill },
    ]) {
      expect(retainTeachingAttempt(startKey, changed, now + 1)).toBe(false);
      expect(sessionStorage.getItem(startKey)).toBe(raw);
    }
    expect(readTeachingAttempt(startKey, "start", now + retention)).toEqual(blocked);
    expect(retainTeachingAttempt(startKey, attempt, now + retention)).toBe(false);
    expect(sessionStorage.getItem(startKey)).toBe(raw);
  });

  it("does not replace an unresolved draft revision, mode or budget", () => {
    const attempt: TeachingDraftAttempt = {
      ...draft(),
      body: { mode: "assistant", max_cost_usd: "1" },
    };
    expect(retainTeachingAttempt(draftKey, attempt, now)).toBe(true);
    const raw = sessionStorage.getItem(draftKey);
    for (const changed of [
      { ...attempt, revision: 3 },
      { ...attempt, body: { mode: "reviewed" } as const },
      { ...attempt, body: { mode: "assistant", max_cost_usd: "2" } as const },
    ])
      expect(retainTeachingAttempt(draftKey, changed, now + 1)).toBe(false);
    expect(sessionStorage.getItem(draftKey)).toBe(raw);
  });

  it("uses the current clock by default and expires exactly at the retention boundary", () => {
    vi.spyOn(Date, "now").mockReturnValue(now);
    expect(retainTeachingAttempt(startKey, start())).toBe(true);
    expect(readTeachingAttempt(startKey, "start")).toEqual({ attempt: start(), blocked: false });
    expect(readTeachingAttempt(startKey, "start", now + retention - 1).blocked).toBe(false);
    expect(readTeachingAttempt(startKey, "start", now + retention)).toEqual(blocked);
  });

  it("clears only when the caller has settled the operation, allowing a fresh request", () => {
    expect(retainTeachingAttempt(startKey, start(), now)).toBe(true);
    expect(clearTeachingAttempt(startKey)).toBe(true);
    expect(readTeachingAttempt(startKey, "start", now)).toEqual(empty);
    const replacement = { ...start(), body: { ...start().body, request_id: ids.other } };
    expect(retainTeachingAttempt(startKey, replacement, now + 1)).toBe(true);
    expect(clearTeachingAttempt(draftKey)).toBe(true);
  });
});

describe("closed, bounded storage data", () => {
  const invalidAttempts: { name: string; value: unknown }[] = [
    { name: "null attempt", value: null },
    { name: "array attempt", value: [] },
    { name: "primitive attempt", value: "start" },
    { name: "unknown kind", value: { ...start(), kind: "fill" } },
    { name: "extra attempt field", value: { ...start(), captured_text: "never keep this" } },
    { name: "missing target", value: { kind: "start", body: start().body } },
    { name: "null Start body", value: { ...start(), body: null } },
    { name: "array Start body", value: { ...start(), body: [] } },
    {
      name: "extra Start field",
      value: { ...start(), body: { ...start().body, password: "never keep this" } },
    },
    { name: "invalid target", value: { ...start(), targetSkillId: "not-a-uuid" } },
    { name: "non-string target", value: { ...start(), targetSkillId: 1 } },
    { name: "draft extra field", value: { ...draft(), parameters: {} } },
    { name: "draft fractional revision", value: { ...draft(), revision: 1.5 } },
    { name: "draft zero revision", value: { ...draft(), revision: 0 } },
    { name: "draft negative revision", value: { ...draft(), revision: -1 } },
    { name: "draft unsafe revision", value: { ...draft(), revision: Number.MAX_SAFE_INTEGER + 1 } },
    { name: "draft string revision", value: { ...draft(), revision: "2" } },
    { name: "draft null body", value: { ...draft(), body: null } },
    { name: "draft array body", value: { ...draft(), body: [] } },
    { name: "draft unknown mode", value: { ...draft(), body: { mode: "automatic" } } },
    {
      name: "reviewed with budget",
      value: { ...draft(), body: { mode: "reviewed", max_cost_usd: "1" } },
    },
    { name: "assistant missing budget", value: { ...draft(), body: { mode: "assistant" } } },
    {
      name: "assistant numeric budget",
      value: { ...draft(), body: { mode: "assistant", max_cost_usd: 1 } },
    },
    {
      name: "assistant invalid budget",
      value: { ...draft(), body: { mode: "assistant", max_cost_usd: "1e1" } },
    },
  ];
  const badStartFields: Record<string, unknown[]> = {
    request_id: [1, "invalid"],
    run_id: [1, "invalid"],
    takeover_id: [1, "invalid"],
    call_id: [1, "", "a".repeat(201)],
    tab_id: [1, "", "a".repeat(201)],
    title: [1, " ", "a".repeat(161)],
    allowed_origins: [
      null,
      [],
      Array(11).fill("https://reports.example"),
      [1],
      ["https://" + "a".repeat(2049) + ".example"],
      ["https://reports.example\nhttps://second.example"],
      ["https://reports.example/private"],
      ["https://reports.example", "https://reports.example"],
    ],
  };
  for (const [field, values] of Object.entries(badStartFields)) {
    values.forEach((value, i) =>
      invalidAttempts.push({
        name: "Start " + field + " refusal " + i,
        value: { ...start(), body: { ...start().body, [field]: value } },
      }),
    );
  }

  it.each(invalidAttempts)("refuses $name without deleting or rewriting it", ({ value }) => {
    const key =
      typeof value === "object" && value !== null && "kind" in value && value.kind === "propose"
        ? draftKey
        : startKey;
    const kind = key === draftKey ? "propose" : "start";
    writeRecord(value, key);
    const raw = sessionStorage.getItem(key);
    expect(readTeachingAttempt(key, kind, now)).toEqual(blocked);
    expect(retainTeachingAttempt(key, value as TeachingAttempt, now)).toBe(false);
    expect(sessionStorage.getItem(key)).toBe(raw);
  });

  it.each([
    { name: "null envelope", value: null },
    { name: "array envelope", value: [] },
    { name: "string envelope", value: "attempt" },
    { name: "extra envelope field", value: { createdAt: now, attempt: start(), raw: "private" } },
    { name: "missing timestamp", value: { attempt: start() } },
    { name: "string timestamp", value: { createdAt: String(now), attempt: start() } },
    { name: "negative timestamp", value: { createdAt: -1, attempt: start() } },
    { name: "future timestamp", value: { createdAt: now + 1, attempt: start() } },
    { name: "expired timestamp", value: { createdAt: now - retention, attempt: start() } },
  ])("blocks $name", ({ value }) => {
    const raw = JSON.stringify(value);
    sessionStorage.setItem(startKey, raw);
    expect(readTeachingAttempt(startKey, "start", now)).toEqual(blocked);
    expect(retainTeachingAttempt(startKey, start(), now)).toBe(false);
    expect(sessionStorage.getItem(startKey)).toBe(raw);
  });

  it.each([
    "{",
    " ".repeat(32_769),
    '{"createdAt":1e309,"attempt":' + JSON.stringify(start()) + "}",
  ])("blocks malformed, oversized or nonfinite records", (raw) => {
    sessionStorage.setItem(startKey, raw);
    expect(readTeachingAttempt(startKey, "start", now)).toEqual(blocked);
    expect(sessionStorage.getItem(startKey)).toBe(raw);
  });

  it.each([NaN, Infinity, -1])("refuses an invalid clock %s", (clock) => {
    writeRecord(start());
    expect(readTeachingAttempt(startKey, "start", clock)).toEqual(blocked);
    expect(retainTeachingAttempt(startKey, start(), clock)).toBe(false);
  });

  it("refuses a requested kind that does not match the stored attempt", () => {
    writeRecord(start());
    expect(readTeachingAttempt(startKey, "propose", now)).toEqual(blocked);
  });

  it.each([
    "unrelated-key",
    "browser-teaching-attempt:" + "a".repeat(2049),
    "browser-teaching-attempt:{",
    "browser-teaching-attempt:null",
    "browser-teaching-attempt:" +
      JSON.stringify([null, ids.org, "start", ids.run, "teaching-call", "main"]),
    "browser-teaching-attempt:" +
      JSON.stringify([ids.owner, "", "start", ids.run, "teaching-call", "main"]),
    teachingAttemptKey(audience, "propose", [ids.session]),
    teachingAttemptKey(audience, "start", [ids.run, "teaching-call"]),
    teachingAttemptKey(audience, "start", [ids.other, "teaching-call", "main"]),
    teachingAttemptKey(audience, "start", [ids.run, "other-call", "main"]),
    teachingAttemptKey(audience, "start", [ids.run, "teaching-call", "other-tab"]),
  ])("refuses a Start namespace/body mismatch", (key) => {
    writeRecord(start(), key);
    expect(readTeachingAttempt(key, "start", now)).toEqual(blocked);
    expect(retainTeachingAttempt(key, start(), now)).toBe(false);
  });

  it.each([
    teachingAttemptKey(audience, "propose", []),
    teachingAttemptKey(audience, "propose", ["not-a-uuid"]),
  ])("refuses a malformed draft identity", (key) => {
    writeRecord(draft(), key);
    expect(readTeachingAttempt(key, "propose", now)).toEqual(blocked);
    expect(retainTeachingAttempt(key, draft(), now)).toBe(false);
  });
});

describe("bounded storage and unavailable persistence", () => {
  it("does not evict an unresolved attempt to admit a twenty-first record", () => {
    expect(retainTeachingAttempt(startKey, start(), now)).toBe(true);
    for (let i = 0; i < 19; i++)
      sessionStorage.setItem("browser-teaching-attempt:reserved-" + i, "unresolved");
    sessionStorage.setItem("unrelated-feature", "kept");
    expect(retainTeachingAttempt(draftKey, draft(), now)).toBe(false);
    expect(retainTeachingAttempt(startKey, start(), now + 1)).toBe(true);
    expect(sessionStorage.length).toBe(21);
    expect(sessionStorage.getItem("unrelated-feature")).toBe("kept");
  });

  it("does not count unrelated keys or a concurrently removed key", () => {
    sessionStorage.setItem("unrelated-feature", "kept");
    vi.spyOn(sessionStorage, "key").mockReturnValueOnce(null);
    expect(retainTeachingAttempt(startKey, start(), now)).toBe(true);
    expect(sessionStorage.getItem("unrelated-feature")).toBe("kept");
  });

  it("blocks recovery and retention when reading storage is unavailable", () => {
    vi.spyOn(sessionStorage, "getItem").mockImplementation(() => {
      throw new Error("Storage unavailable");
    });
    expect(readTeachingAttempt(startKey, "start", now)).toEqual(blocked);
    expect(retainTeachingAttempt(startKey, start(), now)).toBe(false);
  });

  it("refuses when storage enumeration fails", () => {
    sessionStorage.setItem("unrelated-feature", "kept");
    vi.spyOn(sessionStorage, "key").mockImplementation(() => {
      throw new Error("Storage unavailable");
    });
    expect(retainTeachingAttempt(startKey, start(), now)).toBe(false);
  });

  it("refuses a quota failure or silently dropped write", () => {
    const writer = vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
      throw new Error("Quota exceeded");
    });
    expect(retainTeachingAttempt(startKey, start(), now)).toBe(false);
    writer.mockImplementation(() => {});
    expect(retainTeachingAttempt(startKey, start(), now)).toBe(false);
  });

  it("does not claim a silent or failed removal settled an attempt", () => {
    writeRecord(start());
    const remover = vi.spyOn(sessionStorage, "removeItem").mockImplementation(() => {});
    expect(clearTeachingAttempt(startKey)).toBe(false);
    remover.mockImplementation(() => {
      throw new Error("Storage unavailable");
    });
    expect(clearTeachingAttempt(startKey)).toBe(false);
    expect(sessionStorage.getItem(startKey)).not.toBeNull();
  });
});
