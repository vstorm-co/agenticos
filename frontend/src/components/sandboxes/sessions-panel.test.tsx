import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionsPanel } from "./sessions-panel";
import type {
  SandboxConnectionRecord,
  SandboxOperation,
  SandboxOperationList,
  SandboxOperationQuery,
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
  log: null as SandboxOperationList | null,
  /** What a *narrowed* request answers, when a case needs the two to differ. */
  narrowed: null as SandboxOperationList | null,
  logError: null as string | null,
  logLoading: false,
  asked: [] as SandboxOperationQuery[],
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
  useSandboxOperations: (query: SandboxOperationQuery) => {
    state.asked.push(query);
    // A narrowed request is a different request, and the two answers differ - which
    // is the whole point of the filters reaching the server.
    const narrow = Boolean(query.op) || query.failedOnly === true || Boolean(query.query);
    const log = narrow && state.narrowed !== null ? state.narrowed : state.log;
    return { log, isLoading: state.logLoading, error: state.logError };
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
    conversation_is_callers: true,
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
  state.log = { items: [], total: 0, operations: [] };
  state.narrowed = null;
  state.logError = null;
  state.logLoading = false;
  state.asked = [];
});

function operation(overrides: Partial<SandboxOperation> = {}): SandboxOperation {
  return {
    id: "op-1",
    at: new Date(Date.now() - 5_000).toISOString(),
    op: "write",
    target: "/run.py",
    ok: true,
    detail: "",
    duration_ms: 12,
    session_key: "xc-1",
    agent_id: null,
    agent_name: null,
    run_id: null,
    ...overrides,
  };
}

/** A log of `total` matches, of which this page holds `items`. */
function log(items: SandboxOperation[], total = items.length, operations: string[] = []) {
  return { items, total, operations };
}

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
      // The log is read from this platform's own record, which is keyed on the
      // session rather than on the host it was opened through - so the old
      // cross-host mixup cannot arise. What is still worth holding: a log left
      // open over a host switch would be titled for a sandbox the table below no
      // longer lists.
      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));
      expect(screen.getByRole("dialog")).toBeVisible();

      await userEvent.keyboard("{Escape}");
      await userEvent.click(screen.getByRole("combobox", { name: "Host" }));
      await userEvent.click(screen.getByRole("option", { name: "Backup host" }));

      expect(screen.queryByRole("dialog")).toBeNull();
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

      expect(state.asked).toEqual([]);
    });

    it("reads this platform's own record rather than the service's log", async () => {
      // The point of #1061: the service keeps a 200-entry ring buffer in its
      // process memory, so what it dropped could not be asked for and a restart
      // lost every log on the host. These rows answer a week later.
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      expect(state.asked.at(-1)?.sessionKey).toBe("xc-1");
    });

    it("shows the operations, their targets and how long each took", async () => {
      state.log = log([operation()]);
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      expect(screen.getByText("write")).toBeVisible();
      expect(screen.getByText("/run.py")).toBeVisible();
      expect(screen.getByText("12ms")).toBeVisible();
    });

    it("names the agent that performed each operation", async () => {
      // One of the two facts the service's own log cannot carry, and one of the
      // two somebody auditing a sandbox actually came for.
      state.log = log([operation({ agent_name: "JARVIS" })]);
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      expect(within(screen.getByRole("dialog")).getByText("JARVIS")).toBeVisible();
    });

    it("still shows an operation whose agent has since been deleted", async () => {
      // `SET NULL` on the FK, and the read has to survive it: the record of what
      // happened is the whole reason for recording it.
      state.log = log([operation({ agent_id: "a-gone", agent_name: null })]);
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      const dialog = within(screen.getByRole("dialog"));
      expect(dialog.getByText("agent deleted")).toBeVisible();
      expect(dialog.getByText("/run.py")).toBeVisible();
    });

    it("closes again on a second press", async () => {
      render(<SessionsPanel connections={[connection()]} />);
      const toggle = screen.getByRole("button", { name: "Activity of xc-1" });

      await userEvent.click(toggle);
      expect(state.asked.at(-1)?.sessionKey).toBe("xc-1");

      const opened = state.asked.length;
      // Escape rather than the same button: the dialog is over it, and closing a
      // dialog is the dialog's own affair.
      await userEvent.keyboard("{Escape}");

      // Unmounted rather than re-queried with nothing.
      expect(state.asked).toHaveLength(opened);
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

    it("narrows the request rather than an array it already holds", async () => {
      // Which is the difference this table exists for. Filtering a page of fifty
      // is a filter that cannot find the operation somebody came for, because the
      // operation is on page six.
      state.log = log([operation()], 300, ["execute", "write"]);
      render(<SessionsPanel connections={[connection()]} />);
      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));
      const dialog = within(screen.getByRole("dialog"));

      await userEvent.type(dialog.getByPlaceholderText("Search operations"), "pytest");
      await vi.waitFor(() => expect(state.asked.at(-1)?.query).toBe("pytest"));

      await userEvent.click(dialog.getByRole("switch", { name: "Failed only" }));
      expect(state.asked.at(-1)?.failedOnly).toBe(true);
    });

    it("holds a keystroke back rather than asking per letter", async () => {
      // The search is a request, so a round trip per keystroke is both wasteful
      // and prone to answers landing out of order.
      state.log = log([operation()], 300);
      render(<SessionsPanel connections={[connection()]} />);
      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));
      const dialog = within(screen.getByRole("dialog"));

      await userEvent.type(dialog.getByPlaceholderText("Search operations"), "pytest");

      expect(state.asked.map((asked) => asked.query)).not.toContain("pyt");
    });

    it("narrows to one kind of operation, and offers only the kinds it holds", async () => {
      // A filter offering `edit` on a sandbox that has only ever been globbed is a
      // filter that answers nothing, so the list comes from the log itself.
      state.log = log([operation()], 2, ["execute", "write"]);
      render(<SessionsPanel connections={[connection()]} />);
      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));
      const dialog = within(screen.getByRole("dialog"));

      await userEvent.click(dialog.getByRole("combobox", { name: "Operation" }));
      expect(screen.queryByRole("option", { name: "glob_info" })).toBeNull();
      await userEvent.click(screen.getByRole("option", { name: "execute" }));

      expect(state.asked.at(-1)?.op).toBe("execute");
    });

    it("pages a result set larger than one page, and says how many there are", async () => {
      // What the service's log could never do: its `after` is a polling cursor,
      // not a page, so there was nothing to page to and the count could only say
      // how much of the buffer was left.
      state.log = log([operation()], 137);
      render(<SessionsPanel connections={[connection()]} />);
      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));
      const dialog = within(screen.getByRole("dialog"));

      expect(dialog.getByText(/137 operations/)).toBeVisible();

      await userEvent.click(dialog.getByRole("button", { name: "Next page" }));

      expect(state.asked.at(-1)?.skip).toBe(50);
    });

    it("returns to the first page when a filter changes", async () => {
      // Narrowing to nine rows while sitting on page four is an empty table that
      // reads as "nothing matches".
      state.log = log([operation()], 300, ["execute"]);
      render(<SessionsPanel connections={[connection()]} />);
      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));
      const dialog = within(screen.getByRole("dialog"));

      await userEvent.click(dialog.getByRole("button", { name: "Next page" }));
      expect(state.asked.at(-1)?.skip).toBe(50);

      await userEvent.click(dialog.getByRole("switch", { name: "Failed only" }));

      expect(state.asked.at(-1)?.skip).toBe(0);
    });

    it("says no operation matches, rather than that the sandbox did nothing", async () => {
      // The two are different answers and used to render the same sentence: a
      // filter that matched none looked like a sandbox that had never been used.
      state.log = log([operation()], 300, ["execute"]);
      state.narrowed = log([], 0, ["execute"]);
      render(<SessionsPanel connections={[connection()]} />);
      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));
      const dialog = within(screen.getByRole("dialog"));

      await userEvent.click(dialog.getByRole("switch", { name: "Failed only" }));

      expect(dialog.getByText("No operation matches that.")).toBeVisible();
      expect(dialog.queryByText(/Nothing recorded/)).toBeNull();
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

    it("says how long ago each operation was", async () => {
      // With no timestamp anywhere, "now" and "an hour ago" looked the same - and
      // the order is the server's, newest first, so the top row is what the
      // sandbox is doing now.
      state.log = log([
        operation({ id: "op-new", at: new Date(Date.now() - 5_000).toISOString(), op: "execute" }),
        operation({ id: "op-mid", at: new Date(Date.now() - 120_000).toISOString() }),
        operation({ id: "op-old", at: new Date(Date.now() - 3_600_000).toISOString() }),
        // Days matter: these rows are kept for thirty of them, where the
        // service's buffer rarely held an hour.
        operation({ id: "op-ancient", at: new Date(Date.now() - 259_200_000).toISOString() }),
      ]);
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: /Activity of/ }));

      const rows = within(screen.getByRole("dialog")).getAllByRole("row").slice(1);

      expect(rows[0]).toHaveTextContent("execute");
      expect(rows[0]).toHaveTextContent("5s ago");
      expect(rows[1]).toHaveTextContent("2m ago");
      expect(rows[2]).toHaveTextContent("1h ago");
      expect(rows[3]).toHaveTextContent("3d ago");
    });

    it("says nothing about when, rather than a date it cannot read", async () => {
      state.log = log([operation({ at: "not a date" })]);
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      expect(within(screen.getByRole("dialog")).getByText("ago")).toBeVisible();
    });

    it("is a labelled table, and marks an operation that failed", async () => {
      state.log = log([
        operation({ op: "execute", target: "python run.py", ok: false, detail: "exit 1" }),
      ]);
      render(<SessionsPanel connections={[connection()]} />);

      await userEvent.click(screen.getByRole("button", { name: "Activity of xc-1" }));

      // On the shared table primitive, with headers - not a bare <table> in a
      // grey box (#140).
      expect(screen.getByRole("columnheader", { name: "Operation" })).toBeVisible();
      expect(screen.getByText("exit 1")).toBeVisible();
      expect(screen.getByText("execute")).toHaveClass("text-destructive");
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

  it("does not link a conversation the reader cannot open", () => {
    // The chat page lists its owner's threads, and this listing is
    // organization-wide - so a link on somebody else's row landed on an empty
    // sidebar dressed as the conversation.
    state.listing = listing([
      session({ conversation_id: "c-9", scope: "conversation", conversation_is_callers: false }),
    ]);
    render(<SessionsPanel connections={[connection()]} />);

    expect(screen.getByText("one conversation")).toBeVisible();
    expect(screen.queryByRole("link", { name: "one conversation" })).toBeNull();
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
