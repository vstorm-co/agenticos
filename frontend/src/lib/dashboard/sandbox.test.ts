import { describe, expect, it } from "vitest";

import {
  holdsSessions,
  idleLabel,
  memoryLabel,
  primaryConnection,
  scopeKey,
  tenantShare,
  watchableConnections,
} from "./sandbox";
import type {
  SandboxConnectionRecord,
  SandboxSession,
  SandboxSessionList,
} from "@/lib/sandbox-connections-api";

function connection(overrides: Partial<SandboxConnectionRecord> = {}): SandboxConnectionRecord {
  return {
    id: "c-1",
    name: "Local Docker",
    kind: "docker",
    base_url: "http://sandboxd:8080",
    secret_id: "s-1",
    default_runtime: null,
    is_default: false,
    is_active: true,
    created_at: "2026-08-03T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function session(overrides: Partial<SandboxSession> = {}): SandboxSession {
  return {
    session_id: "cc-abcd1234-ffff",
    runtime: "python",
    alive: true,
    state: "running",
    created_at: 1_760_000_000,
    last_activity: 1_760_000_100,
    idle_seconds: 12,
    usage: null,
    agent_id: "a-1",
    conversation_id: "conv-1",
    scope: "conversation",
    ...overrides,
  };
}

function listing(overrides: Partial<SandboxSessionList> = {}): SandboxSessionList {
  return { sessions: [], limit: null, open_limit: null, tenant_limit: null, ...overrides };
}

describe("watchableConnections", () => {
  it("drops a connection nobody's agent can reach any more", () => {
    const rows = watchableConnections([
      connection({ id: "live" }),
      connection({ id: "retired", is_active: false }),
    ]);

    expect(rows.map((row) => row.id)).toEqual(["live"]);
  });
});

describe("primaryConnection", () => {
  it("is the default, because that is the host an agent naming none gets", () => {
    const chosen = primaryConnection([
      connection({ id: "other" }),
      connection({ id: "default", is_default: true }),
    ]);

    expect(chosen?.id).toBe("default");
  });

  it("falls back to the first active host rather than showing an empty card", () => {
    const chosen = primaryConnection([
      connection({ id: "retired", is_active: false, is_default: true }),
      connection({ id: "running" }),
    ]);

    expect(chosen?.id).toBe("running");
  });

  it("is null for a deployment that registered none", () => {
    expect(primaryConnection([])).toBeNull();
  });
});

describe("holdsSessions", () => {
  it("is true of a container host, whose sessions we opened and can count", () => {
    expect(holdsSessions(connection({ kind: "docker" }))).toBe(true);
  });

  it("is false of Daytona, which is not the same thing as an idle host", () => {
    // Both answer with an empty list, and the `kind` the service puts beside it
    // is dropped by the response model - so the row is the only witness.
    expect(holdsSessions(connection({ kind: "daytona" }))).toBe(false);
  });
});

describe("tenantShare", () => {
  it("divides this organization's sessions by the ceiling that applies to it", () => {
    const share = tenantShare(listing({ sessions: [session(), session()], tenant_limit: 8 }));

    expect(share).toEqual({ used: 2, limit: 8, percent: 25 });
  });

  it("never divides by the host's own ceilings, which count every tenant", () => {
    // `limit` 40 and `open_limit` 20 are the whole host's; two sessions are ours.
    // 2/40 would read as 5% of a ceiling that is not the one refusing us.
    const share = tenantShare(
      listing({ sessions: [session(), session()], limit: 40, open_limit: 20 }),
    );

    expect(share).toEqual({ used: 2, limit: null, percent: null });
  });

  it("answers with no percentage when the ceiling is zero rather than dividing by it", () => {
    expect(tenantShare(listing({ tenant_limit: 0 })).percent).toBeNull();
  });

  it("clamps at full, so a host over its own ceiling does not draw past the track", () => {
    const share = tenantShare(
      listing({ sessions: [session(), session(), session()], tenant_limit: 2 }),
    );

    expect(share.percent).toBe(100);
  });
});

describe("scopeKey", () => {
  it.each([
    ["agent", "scope.agent"],
    ["conversation", "scope.conversation"],
    ["channel", "scope.channel"],
    ["user", "scope.user"],
  ])("%s shares a sandbox with %s", (scope, expected) => {
    expect(scopeKey(scope)).toBe(expected);
  });

  it("reads no scope as a single run, which has no workspace row by design", () => {
    expect(scopeKey(null)).toBe("scope.run");
  });

  it("says a scope it does not know is unknown instead of guessing the widest one", () => {
    // Who may read a sandbox's files is exactly what the scope says; calling a
    // sixth one "the whole agent" describes the wrong set of people.
    expect(scopeKey("workspace")).toBe("scope.unknown");
  });
});

describe("idleLabel", () => {
  it.each([
    [12, "idle.seconds", 12],
    [59.6, "idle.seconds", 60],
    [90, "idle.minutes", 2],
    [7_200, "idle.hours", 2],
  ])("%ss idle -> %s %s", (seconds, key, count) => {
    expect(idleLabel(seconds)).toEqual({ key, count });
  });
});

describe("memoryLabel", () => {
  it("reads a sample against the ceiling of that sandbox alone", () => {
    const label = memoryLabel(
      session({ usage: { memory_bytes: 64 * 1024 * 1024, memory_limit_bytes: 512 * 1024 * 1024 } }),
    );

    expect(label).toEqual({ used: "64.0 MB", limit: "512.0 MB" });
  });

  it("reads a sample the host set no ceiling for", () => {
    const label = memoryLabel(session({ usage: { memory_bytes: 1024, memory_limit_bytes: null } }));

    expect(label).toEqual({ used: "1.0 KB", limit: null });
  });

  it("is null when usage was never sampled, which is the normal case", () => {
    expect(memoryLabel(session({ usage: null }))).toBeNull();
  });

  it("is null when the host answered with a usage block holding no memory figure", () => {
    expect(memoryLabel(session({ usage: { cpu_percent: 4 } }))).toBeNull();
    expect(memoryLabel(session({ usage: { memory_bytes: null } }))).toBeNull();
  });
});
