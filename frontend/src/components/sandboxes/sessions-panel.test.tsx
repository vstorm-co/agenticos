import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionsPanel } from "./sessions-panel";
import type {
  SandboxConnectionRecord,
  SandboxEventList,
  SandboxSession,
  SandboxSessionList,
} from "@/lib/sandbox-connections-api";

const state = vi.hoisted(() => ({
  listing: null as SandboxSessionList | null,
  sessionsError: null as string | null,
  sessionsLoading: false,
  usageAsked: [] as boolean[],
  connectionsAsked: [] as (string | null)[],
  log: null as SandboxEventList | null,
  logError: null as string | null,
  logLoading: false,
  watched: [] as (string | null)[],
}));

vi.mock("@/hooks", () => ({
  useSandboxSessions: (id: string | null, usage: boolean) => {
    state.usageAsked.push(usage);
    state.connectionsAsked.push(id);
    return {
      listing: state.listing,
      isLoading: state.sessionsLoading,
      error: state.sessionsError,
    };
  },
  useSandboxEvents: (_id: string | null, sessionId: string | null) => {
    state.watched.push(sessionId);
    return { log: state.log, isLoading: state.logLoading, error: state.logError };
  },
}));

function connection(overrides: Partial<SandboxConnectionRecord> = {}): SandboxConnectionRecord {
  return {
    id: "c-1",
    name: "Local Docker",
    kind: "docker",
    base_url: "http://sandboxd:8080",
    secret_id: "s-1",
    default_runtime: "python",
    is_default: true,
    is_active: true,
    created_at: "2026-08-03T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function session(overrides: Partial<SandboxSession> = {}): SandboxSession {
  return {
    session_id: "xc-1",
    runtime: "python",
    alive: true,
    state: "running",
    created_at: 1,
    last_activity: 2,
    idle_seconds: 30,
    usage: null,
    agent_id: "a-1",
    conversation_id: "conv-1",
    scope: "conversation",
    ...overrides,
  };
}

function listing(sessions: SandboxSession[]): SandboxSessionList {
  return { sessions, limit: null, open_limit: null, tenant_limit: null };
}

beforeEach(() => {
  state.listing = { sessions: [session()], limit: 20, open_limit: null, tenant_limit: 5 };
  state.sessionsError = null;
  state.sessionsLoading = false;
  state.usageAsked = [];
  state.connectionsAsked = [];
  state.log = { events: [], latest_seq: 0 };
  state.logError = null;
  state.logLoading = false;
  state.watched = [];
});

describe("SessionsPanel", () => {
  it("explains that nothing can be listed without a container connection", () => {
    render(<SessionsPanel connections={[]} />);

    expect(screen.getByText("No container connection registered")).toBeVisible();
    // A tab that opens onto nothing is worse than silence, so the empty state
    // says where to register one.
    expect(screen.getByText(/Register one under Connections/)).toBeVisible();
  });

  it("counts this organization's sandboxes against what it is allowed", () => {
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText(/1 of this organization's sandboxes, out of 5 allowed/)).toBeVisible();
  });

  it("says nothing about a ceiling the service did not report", () => {
    state.listing = listing([]);
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.queryByText(/out of/)).toBeNull();
  });

  describe("the host", () => {
    it("is named, and watched by default where an unnamed agent runs", () => {
      render(
        <SessionsPanel
          connections={[
            connection({ id: "c-a", name: "Backup host", is_default: false }),
            connection({ id: "c-b", name: "Primary host", is_default: true }),
          ]}
        />,
      );

      expect(screen.getByText("Running on Primary host")).toBeVisible();
      expect(state.connectionsAsked.at(-1)).toBe("c-b");
    });

    it("offers no selector when only one host is registered", () => {
      render(<SessionsPanel connections={[connection()]} />);

      expect(screen.queryByRole("combobox", { name: "Host" })).toBeNull();
    });

    it("lets an operator switch to another registered host", async () => {
      render(
        <SessionsPanel
          connections={[
            connection({ id: "c-a", name: "Primary host", is_default: true }),
            connection({ id: "c-b", name: "Backup host", is_default: false }),
          ]}
        />,
      );

      await userEvent.click(screen.getByRole("combobox", { name: "Host" }));
      await userEvent.click(screen.getByRole("option", { name: "Backup host" }));

      expect(screen.getByText("Running on Backup host")).toBeVisible();
      expect(state.connectionsAsked.at(-1)).toBe("c-b");
    });
  });

  describe("search", () => {
    it("narrows the table to what matches, without hiding that nothing did", async () => {
      state.listing = listing([
        session({ session_id: "xc-python", runtime: "python" }),
        session({ session_id: "xc-node", runtime: "node" }),
      ]);
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.type(screen.getByRole("textbox", { name: "Search sessions" }), "node");
      expect(screen.getByText("xc-node")).toBeVisible();
      expect(screen.queryByText("xc-python")).toBeNull();

      await userEvent.type(screen.getByRole("textbox", { name: "Search sessions" }), "xyz");
      // "Nothing running" would be a lie - two sandboxes are; none match.
      expect(screen.getByText("No running sandbox matches that.")).toBeVisible();
    });
  });

  describe("sort", () => {
    it("orders by idle time on the idle header", async () => {
      state.listing = listing([
        session({ session_id: "xc-fresh", idle_seconds: 30 }),
        session({ session_id: "xc-stale", idle_seconds: 7200 }),
      ]);
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Idle" }));

      const rows = screen.getAllByRole("row").slice(1);
      expect(within(rows[0]!).getByText("xc-stale")).toBeVisible();
      expect(within(rows[1]!).getByText("xc-fresh")).toBeVisible();
    });

    it("orders by session id on the session header", async () => {
      state.listing = listing([session({ session_id: "xc-a" }), session({ session_id: "xc-b" })]);
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Session" }));

      const rows = screen.getAllByRole("row").slice(1);
      expect(within(rows[0]!).getByText("xc-b")).toBeVisible();
      expect(within(rows[1]!).getByText("xc-a")).toBeVisible();
    });

    it("orders by memory on the memory header, unsampled rows last", async () => {
      state.listing = listing([
        session({ session_id: "xc-unsampled", usage: null }),
        session({
          session_id: "xc-small",
          usage: { memory_bytes: 1048576, memory_limit_bytes: null },
        }),
        session({
          session_id: "xc-big",
          usage: { memory_bytes: 536870912, memory_limit_bytes: null },
        }),
      ]);
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Memory" }));

      const rows = screen.getAllByRole("row").slice(1);
      expect(within(rows[0]!).getByText("xc-big")).toBeVisible();
      expect(within(rows[1]!).getByText("xc-small")).toBeVisible();
      expect(within(rows[2]!).getByText("xc-unsampled")).toBeVisible();
    });
  });

  it("names what shares each sandbox rather than printing a scope keyword", () => {
    state.listing = listing([
      session({ session_id: "a", scope: "channel" }),
      session({ session_id: "b", scope: "user" }),
      session({ session_id: "c", scope: "agent" }),
      session({ session_id: "d", scope: null }),
    ]);
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText("one channel")).toBeVisible();
    expect(screen.getByText("one person")).toBeVisible();
    expect(screen.getByText("the whole agent")).toBeVisible();
    // No row of ours: a run-scoped sandbox is deleted the moment the run ends.
    expect(screen.getByText("a single run")).toBeVisible();
  });

  it("does not sample memory until somebody asks", async () => {
    // The service pays a daemon round trip per sandbox for it.
    render(<SessionsPanel connections={[connection()]} />);
    expect(state.usageAsked[0]).toBe(false);

    await userEvent.click(screen.getByLabelText("Sample memory and CPU"));

    expect(state.usageAsked.at(-1)).toBe(true);
  });

  it("shows memory against its own ceiling once sampled", () => {
    state.listing = listing([
      session({ usage: { memory_bytes: 104857600, memory_limit_bytes: 536870912 } }),
    ]);
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText("100 MiB / 512 MiB")).toBeVisible();
  });

  it("shows what was sampled even where there is no ceiling to compare it to", () => {
    state.listing = listing([
      session({ usage: { memory_bytes: 104857600, memory_limit_bytes: null } }),
    ]);
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText("100 MiB")).toBeVisible();
  });

  it.each([
    [30, "30s"],
    [300, "5m"],
    [7200, "2h"],
  ])("reads an idle time of %i seconds as %s", (seconds, expected) => {
    state.listing = listing([session({ idle_seconds: seconds })]);
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText(expected)).toBeVisible();
  });

  it("distinguishes a hibernated sandbox from a dead one", () => {
    // It was stopped to free a slot; its files and its log are still there.
    state.listing = listing([session({ alive: false, state: "hibernated" })]);
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText("hibernated")).toBeVisible();
  });

  it("says nothing is running rather than showing an empty table", () => {
    state.listing = listing([]);
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText(/Nothing running/)).toBeVisible();
  });

  it("reports a host that did not answer instead of looking idle", () => {
    // An empty table and an unreachable service are otherwise the same pixels.
    state.listing = null;
    state.sessionsError = "The sandbox service at http://sandboxd:8080 did not answer";
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText(/did not answer/)).toBeVisible();
  });

  it("claims neither idleness nor failure while the host is being asked", () => {
    state.listing = null;
    state.sessionsLoading = true;
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.queryByText(/Nothing running/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  describe("the activity log", () => {
    it("is not even mounted until a session is opened", () => {
      // Stronger than passing a null id: the query is never constructed, so a
      // panel nobody opened costs no request and no cache entry.
      render(<SessionsPanel connections={[connection()]} />);

      expect(state.watched).toEqual([]);
    });

    it("shows the operations, their targets and how long each took", async () => {
      state.log = {
        events: [
          { seq: 1, at: 1, op: "write", target: "/run.py", ok: true, detail: "", duration_ms: 12 },
        ],
        latest_seq: 1,
      };
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      expect(screen.getByText("write")).toBeVisible();
      expect(screen.getByText("/run.py")).toBeVisible();
      expect(screen.getByText("12ms")).toBeVisible();
    });

    it("closes again on a second press", async () => {
      render(<SessionsPanel connections={[connection()]} />);
      const toggle = screen.getByRole("button", { name: "Activity of xc-1" });

      await userEvent.click(toggle);
      expect(state.watched.at(-1)).toBe("xc-1");

      const opened = state.watched.length;
      await userEvent.click(toggle);

      // Unmounted rather than re-queried with nothing.
      expect(state.watched).toHaveLength(opened);
      expect(screen.queryByText(/Nothing recorded/)).toBeNull();
    });

    it("says a session has recorded nothing rather than showing an empty box", async () => {
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      expect(screen.getByText(/Nothing recorded/)).toBeVisible();
    });

    it("says the log itself could not be read", async () => {
      state.log = null;
      state.logError = "That activity log could not be read";
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      expect(screen.getByText("That activity log could not be read")).toBeVisible();
    });

    it("draws a placeholder while the log is being fetched", async () => {
      state.log = null;
      state.logLoading = true;
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      expect(document.querySelector(".h-24")).not.toBeNull();
    });

    it("is a labelled table, and marks an operation that failed", async () => {
      state.log = {
        events: [
          {
            seq: 1,
            at: 1,
            op: "exec",
            target: "python run.py",
            ok: false,
            detail: "exit 1",
            duration_ms: 40,
          },
        ],
        latest_seq: 1,
      };
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      // On the shared table primitive, with headers - not a bare <table> in a
      // grey box (#140).
      expect(screen.getByRole("columnheader", { name: "Operation" })).toBeVisible();
      expect(screen.getByText("exit 1")).toBeVisible();
      expect(screen.getByText("exec")).toHaveClass("text-destructive");
    });
  });
});
