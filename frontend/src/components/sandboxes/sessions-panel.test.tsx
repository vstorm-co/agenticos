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
  policy: null as { idle_timeout: number | null } | null,
  agents: [] as { id: string; name: string }[],
  listing: null as SandboxSessionList | null,
  sessionsError: null as string | null,
  sessionsLoading: false,
  usageAsked: [] as boolean[],
  connectionsAsked: [] as (string | null)[],
  log: null as SandboxEventList | null,
  logError: null as string | null,
  logLoading: false,
  watched: [] as { connection: string | null; session: string | null }[],
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
  useSandboxEvents: (id: string | null, sessionId: string | null) => {
    state.watched.push({ connection: id, session: sessionId });
    return { log: state.log, isLoading: state.logLoading, error: state.logError };
  },
  // The ceilings in force, which is what turns an idle time into a countdown.
  useSandboxPolicy: () => ({ policy: state.policy, isLoading: false, error: null }),
  // Names for the agent ids the host answers with.
  useAgents: () => ({ agents: state.agents, isLoading: false, error: null }),
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
  state.policy = null;
  state.agents = [];
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

    it("closes an open activity log when the host is switched", async () => {
      render(
        <SessionsPanel
          connections={[
            connection({ id: "c-a", name: "Primary host", is_default: true }),
            connection({ id: "c-b", name: "Backup host", is_default: false }),
          ]}
        />,
      );
      // The log opens in a dialog, which takes the page behind it out of reach -
      // so switching host while one is open is no longer a sequence a person can
      // perform. The guard stays because a session id names a sandbox on *one*
      // host, and this is what remains observable: nothing asks the new host for
      // the old host's session.
      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));
      expect(screen.getByRole("dialog")).toBeVisible();

      await userEvent.keyboard("{Escape}");
      await userEvent.click(screen.getByRole("combobox", { name: "Host" }));
      await userEvent.click(screen.getByRole("option", { name: "Backup host" }));

      expect(screen.queryByRole("dialog")).toBeNull();
      expect(state.watched).not.toContainEqual({ connection: "c-b", session: "xc-1" });
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

  it("reads a container that has barely started in kibibytes", () => {
    // A sandbox opened and not yet used holds a few hundred KiB, and rounding that
    // to `0 MiB` reads as a sample that failed.
    state.listing = listing([
      session({ usage: { memory_bytes: 348160, memory_limit_bytes: 2147483648 } }),
    ]);
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText("340 KiB / 2.0 GiB")).toBeVisible();
  });

  it("reads a container's gigabytes in gigabytes", () => {
    // `workbench` runs with a 2 GiB ceiling, so "1740 MiB / 2048 MiB" was the
    // normal reading - a four-digit number against another four-digit number.
    state.listing = listing([
      session({ usage: { memory_bytes: 1825361100, memory_limit_bytes: 2147483648 } }),
    ]);
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText("1.7 GiB / 2.0 GiB")).toBeVisible();
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
      expect(state.watched.at(-1)).toEqual({ connection: "c-1", session: "xc-1" });

      const opened = state.watched.length;
      // Escape rather than the same button: the dialog is over it, and closing a
      // dialog is the dialog's own affair.
      await userEvent.keyboard("{Escape}");

      // Unmounted rather than re-queried with nothing.
      expect(state.watched).toHaveLength(opened);
      expect(screen.queryByRole("dialog")).toBeNull();
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

    it("searches, filters by operation, and can show the failures alone", async () => {
      // Three hundred operations is what a sandbox that has been working looks
      // like, and somebody who opened this log came to find one of them.
      const now = Date.now() / 1000;
      state.log = {
        events: [
          {
            seq: 1,
            at: now - 60,
            op: "glob",
            target: "**/*.py",
            ok: true,
            detail: "3 matches",
            duration_ms: 20,
          },
          {
            seq: 2,
            at: now - 30,
            op: "exec",
            target: "pytest -q",
            ok: false,
            detail: "exit 1",
            duration_ms: 900,
          },
          {
            seq: 3,
            at: now - 10,
            op: "write",
            target: "notes.md",
            ok: true,
            detail: "",
            duration_ms: 5,
          },
        ],
        latest_seq: 3,
      };
      render(<SessionsPanel connections={[connection()]} />);
      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      const dialog = within(screen.getByRole("dialog"));
      expect(dialog.getByText("3 of 3 operations")).toBeVisible();

      await userEvent.type(dialog.getByPlaceholderText("Search operations"), "pytest");
      expect(dialog.getByText("1 of 3 operations")).toBeVisible();
      expect(dialog.queryByText("notes.md")).toBeNull();

      await userEvent.clear(dialog.getByPlaceholderText("Search operations"));
      await userEvent.click(dialog.getByRole("switch", { name: "Failed only" }));

      expect(dialog.getByText("pytest -q")).toBeVisible();
      expect(dialog.queryByText("notes.md")).toBeNull();
    });

    it("narrows to one kind of operation, and offers only the kinds it holds", async () => {
      // A filter offering `edit` on a sandbox that has only ever been globbed is a
      // filter that answers nothing, so the list is built from the log.
      const now = Math.round(Date.now() / 1000);
      state.log = {
        events: [
          {
            seq: 1,
            at: now - 60,
            op: "glob",
            target: "**/*.py",
            ok: true,
            detail: "",
            duration_ms: 20,
          },
          {
            seq: 2,
            at: now - 30,
            op: "exec",
            target: "pytest -q",
            ok: true,
            detail: "",
            duration_ms: 900,
          },
        ],
        latest_seq: 2,
      };
      render(<SessionsPanel connections={[connection()]} />);
      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));
      const dialog = within(screen.getByRole("dialog"));

      await userEvent.click(dialog.getByRole("combobox", { name: "Operation" }));
      expect(screen.queryByRole("option", { name: "write" })).toBeNull();
      await userEvent.click(screen.getByRole("option", { name: "exec" }));

      expect(dialog.getByText("pytest -q")).toBeVisible();
      expect(dialog.queryByText("**/*.py")).toBeNull();
      expect(dialog.getByText("1 of 2 operations")).toBeVisible();
    });

    it("says when the service has dropped the earlier operations", async () => {
      // The service keeps a fixed number of entries per session, so a log that
      // starts above sequence 1 has lost its beginning. Without this it simply
      // ends, and somebody looking for what a sandbox did an hour ago reads that
      // as "it did nothing" - and there is nothing to page to, because what the
      // service no longer holds it cannot be asked for.
      state.log = {
        events: [
          { seq: 201, at: 1, op: "exec", target: "ls", ok: true, detail: "", duration_ms: 3 },
        ],
        latest_seq: 201,
      };
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      expect(
        within(screen.getByRole("dialog")).getByText(/Earlier ones are no longer kept/),
      ).toBeVisible();
    });

    it("says nothing of the kind for a log that has its beginning", async () => {
      state.log = {
        events: [{ seq: 1, at: 1, op: "exec", target: "ls", ok: true, detail: "", duration_ms: 3 }],
        latest_seq: 1,
      };
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      expect(screen.queryByText(/Earlier ones are no longer kept/)).toBeNull();
    });

    it("offers only the operations this log holds", async () => {
      // A filter offering `edit` on a sandbox that has only ever been globbed is
      // a filter that answers nothing.
      state.log = {
        events: [
          { seq: 1, at: 1, op: "glob", target: "**/*", ok: true, detail: "", duration_ms: 2 },
        ],
        latest_seq: 1,
      };
      render(<SessionsPanel connections={[connection()]} />);
      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      const dialog = within(screen.getByRole("dialog"));
      await userEvent.click(dialog.getByRole("combobox", { name: "Operation" }));

      expect(screen.getByRole("option", { name: "glob" })).toBeVisible();
      expect(screen.queryByRole("option", { name: "exec" })).toBeNull();
    });

    it("opens in a dialog that names whose sandbox it is", async () => {
      // Expanded under the table it was a table inside a table, with its columns
      // lining up with none of the ones above and the row it belonged to pushed
      // out of sight.
      state.agents = [{ id: "a-1", name: "JARVIS" }];
      state.listing = listing([session({ agent_id: "a-1" })]);
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      const dialog = screen.getByRole("dialog");

      expect(within(dialog).getByText("JARVIS's sandbox")).toBeVisible();
      // More than once: the header names it, and the empty log says which session
      // it found nothing for.
      expect(within(dialog).getAllByText("xc-1").length).toBeGreaterThan(0);
      expect(within(dialog).getByText(/a file's contents/)).toBeVisible();
    });

    it("puts the newest operation first, and says how long ago it was", async () => {
      // The service answers in the order it recorded them, so a log read to find
      // out what a sandbox is doing *now* had the answer at the bottom of a scroll
      // box - and with no timestamp anywhere, "now" and "an hour ago" looked the
      // same.
      const now = Date.now() / 1000;
      state.log = {
        events: [
          {
            seq: 1,
            at: now - 3600,
            op: "write",
            target: "old.txt",
            ok: true,
            detail: "",
            duration_ms: 4,
          },
          {
            seq: 2,
            at: now - 5,
            op: "exec",
            target: "python run.py",
            ok: true,
            detail: "",
            duration_ms: 40,
          },
        ],
        latest_seq: 2,
      };
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: /Activity of/ }));

      // Inside the dialog, which is what the log opens in now - the page's own
      // table is still behind it.
      const rows = within(screen.getByRole("dialog")).getAllByRole("row").slice(1);

      expect(rows[0]).toHaveTextContent("exec");
      expect(rows[0]).toHaveTextContent("5s ago");
      expect(rows[1]).toHaveTextContent("1h ago");
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

describe("what the row says about a sandbox", () => {
  it("names the agent that opened it, with the key underneath", () => {
    // A column of `xc-40bfd3cc-ca1b1445-d9bdc4992aba470eb26e8716d3c77aaa` answers
    // no question anybody brought to this page.
    state.agents = [{ id: "a-1", name: "JARVIS" }];
    state.listing = listing([session({ agent_id: "a-1" })]);

    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText("JARVIS")).toBeVisible();
    expect(screen.getByText(/xc-/)).toBeVisible();
  });

  it("says when an idle sandbox will be reaped", () => {
    // `29m` measured against nothing is not the number an operator came for.
    state.policy = { idle_timeout: 1800 };
    state.listing = listing([session({ idle_seconds: 1740 })]);

    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText("reaped in 1m")).toBeVisible();
  });

  it("marks a countdown only once it is nearly out", () => {
    // Amber on every row is amber nobody reads. A sandbox with half an hour left
    // is not the one an operator is looking for.
    state.policy = { idle_timeout: 1800 };
    state.listing = listing([session({ idle_seconds: 60 })]);

    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText("reaped in 29m")).not.toHaveClass("text-amber-600");
  });

  it("names a sandbox no agent opened as belonging to none", () => {
    // The service answers with a null agent for a sandbox opened outside a run.
    state.agents = [{ id: "a-1", name: "JARVIS" }];
    state.listing = listing([session({ agent_id: null })]);

    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText("An agent")).toBeVisible();
  });

  it("counts down for a running sandbox only", () => {
    // A hibernated one has already been stopped; there is nothing to count.
    state.policy = { idle_timeout: 1800 };
    state.listing = listing([session({ alive: false, state: "hibernated", idle_seconds: 1740 })]);

    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.queryByText(/reaped in/)).toBeNull();
  });

  it("links the conversation a sandbox belongs to", () => {
    state.listing = listing([session({ conversation_id: "c-9", scope: "conversation" })]);

    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByRole("link", { name: /conversation/i })).toHaveAttribute(
      "href",
      "/chat?id=c-9",
    );
  });
});
