import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as renderBare, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SandboxCapacityWidget } from "./sandbox-capacity";
import { SandboxPolicyWidget } from "./sandbox-policy";
import { SandboxSessionsWidget } from "./sandbox-sessions";
import { ApiError, apiClient } from "@/lib/api-client";
import type { Period } from "@/lib/dashboard/period";
import type {
  SandboxConnectionRecord,
  SandboxEvent,
  SandboxPolicy,
  SandboxRuntime,
  SandboxSession,
  SandboxSessionList,
} from "@/lib/sandbox-connections-api";

/**
 * The sandbox cards against a host that answers - and against one that does not.
 *
 * `next-intl` is not stubbed here (see `vitest.setup.ts`), so every assertion is
 * on the copy a reader sees. That matters most for the figures: "3 of 8" proves
 * the card divided by the ceiling that applies to this organization, and a test
 * asserting on a key could not tell that from "3 of 40".
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});

/** Every sandbox card ignores the period; one value serves all of them. */
const PERIOD: Period = { preset: "30d", from: "2026-07-07", to: "2026-08-05" };

function render(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderBare(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

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
    session_id: "cc-abcd1234-1111",
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

function event(overrides: Partial<SandboxEvent> = {}): SandboxEvent {
  return {
    seq: 1,
    at: 1_760_000_050,
    op: "write_file",
    target: "/workspace/report.py",
    ok: true,
    detail: "",
    duration_ms: 18.4,
    ...overrides,
  };
}

function runtime(overrides: Partial<SandboxRuntime> = {}): SandboxRuntime {
  return {
    alias: "python",
    image: "python:3.12-slim",
    description: "Python with the standard library",
    builds: false,
    mem_limit: "512m",
    cpus: 1,
    network_mode: "none",
    ...overrides,
  };
}

interface HostFixture {
  connection: SandboxConnectionRecord;
  listing?: Partial<SandboxSessionList>;
  /** The sentence a host answers with instead of a listing. */
  fails?: string;
  /** Per session id: the log it answers with, or the sentence it fails with. */
  logs?: Record<string, SandboxEvent[] | string>;
  /** What it allows, or the sentence it fails the policy call with. */
  allows?: Partial<SandboxPolicy> | string;
}

/**
 * The agents this caller can read - where a session row's name comes from.
 * Reset per test, so one can drop the row a session points at.
 */
let agentRows: { id: string; name: string }[] = [];

const SESSIONS = /^\/sandbox-connections\/([^/]+)\/sessions\?/;
const EVENTS = /^\/sandbox-connections\/([^/]+)\/sessions\/([^/?]+)\/events/;
const POLICY = /^\/sandbox-connections\/([^/]+)\/policy$/;

/** A deployment's registered hosts, each answering for itself. */
function deployment(...hosts: HostFixture[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/sandbox-connections") {
      return { items: hosts.map((host) => host.connection), total: hosts.length };
    }
    if (path === "/agents") {
      return { items: agentRows, total: agentRows.length };
    }
    const allowed = POLICY.exec(path);
    if (allowed !== null) {
      const answer = hosts.find((candidate) => candidate.connection.id === allowed[1])?.allows;
      if (typeof answer === "string") throw new ApiError(502, answer);
      return {
        kind: "docker",
        runtimes: [],
        default_runtime: null,
        max_sessions: null,
        max_open_sessions: null,
        max_sessions_per_tenant: null,
        idle_timeout: null,
        workspace_root: null,
        persist_containers: null,
        ...answer,
      };
    }
    const log = EVENTS.exec(path);
    if (log !== null) {
      const answer = hosts.find((candidate) => candidate.connection.id === log[1])?.logs?.[
        log[2] as string
      ];
      if (typeof answer === "string") throw new ApiError(502, answer);
      return { events: answer ?? [], latest_seq: answer?.at(-1)?.seq ?? 0 };
    }
    const asked = SESSIONS.exec(path);
    if (asked !== null) {
      const host = hosts.find((candidate) => candidate.connection.id === asked[1]);
      if (host?.fails !== undefined) throw new ApiError(502, host.fails);
      const answer = {
        sessions: [] as SandboxSession[],
        limit: null,
        open_limit: null,
        tenant_limit: null,
        ...host?.listing,
      };
      // The service samples memory and CPU only when asked to, so neither does
      // this: a fixture that always carried a usage block would let a card pass
      // that reads memory without ever paying for it.
      if (path.endsWith("usage=true")) return answer;
      return { ...answer, sessions: answer.sessions.map((row) => ({ ...row, usage: null })) };
    }
    throw new ApiError(404, `nothing serves ${path}`);
  });
}

/** Which hosts the card actually asked about. */
function sessionsAskedFor(): string[] {
  return vi
    .mocked(apiClient.get)
    .mock.calls.map(([path]) => SESSIONS.exec(path)?.[1])
    .filter((id): id is string => id !== undefined);
}

/** Which hosts were asked what they allow. */
function policiesAskedFor(): string[] {
  return vi
    .mocked(apiClient.get)
    .mock.calls.map(([path]) => POLICY.exec(path)?.[1])
    .filter((id): id is string => id !== undefined);
}

/** Whether the card ever paid for a usage sample, and how often. */
function sampledUsage(): string[] {
  return vi
    .mocked(apiClient.get)
    .mock.calls.map(([path]) => path)
    .filter((path) => SESSIONS.test(path) && path.endsWith("usage=true"));
}

function tracks(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("[style*='width']")).map(
    (element) => element.className,
  );
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  agentRows = [{ id: "a-1", name: "Support triage" }];
});

describe("the sandbox capacity card", () => {
  it("counts this organization's sandboxes against the ceiling that applies to it", async () => {
    deployment({
      connection: connection({ name: "sandboxd-eu" }),
      listing: { sessions: [session(), session(), session()], tenant_limit: 8 },
    });

    render(<SandboxCapacityWidget title="Sandbox capacity" hint="" period={PERIOD} />);

    expect(await screen.findByText("3 of 8")).toBeInTheDocument();
    expect(screen.getByText("sandboxd-eu")).toBeInTheDocument();
  });

  it("never divides by the host's ceilings, which count every tenant on it", async () => {
    // The whole host allows 40 resident and 20 open; two of them are ours. "2 of
    // 40" would name a ceiling that is not the one refusing us a session, so
    // there is no fraction here at all - only what we hold.
    deployment({
      connection: connection(),
      listing: { sessions: [session(), session()], limit: 40, open_limit: 20 },
    });

    const { container } = render(
      <SandboxCapacityWidget title="Sandbox capacity" hint="" period={PERIOD} />,
    );

    expect(await screen.findByText("2 open")).toBeInTheDocument();
    expect(screen.queryByText("2 of 40")).not.toBeInTheDocument();
    expect(screen.queryByText("2 of 20")).not.toBeInTheDocument();
    // Neither ceiling reaches the card at all, in any wording: this asserts on
    // the rendered text rather than on two guessed phrasings, because the
    // failure being guarded is a plausible-looking ratio and there are several
    // ways to write one.
    expect(container.textContent).not.toContain("40");
    expect(container.textContent).not.toContain("20");
    // And no bar either: a track needs a denominator this response cannot give.
    expect(tracks(container)).toEqual([]);
  });

  it("says on screen that how full the host is cannot be shown, and what that means", async () => {
    // The figure a reader needs is absent, and absence is not self-explaining.
    // Without this sentence, being refused a sandbox while the card shows room
    // to spare reads as the card being wrong.
    deployment({
      connection: connection(),
      listing: { sessions: [session()], tenant_limit: 8 },
    });

    render(<SandboxCapacityWidget title="Sandbox capacity" hint="" period={PERIOD} />);

    expect(await screen.findByText(/How full a host itself is cannot be shown here/)).toBeVisible();
    expect(screen.getByText(/somebody else filled the host/)).toBeVisible();
  });

  it("says one sandbox is open rather than building the plural from English", async () => {
    deployment({ connection: connection(), listing: { sessions: [session()] } });

    render(<SandboxCapacityWidget title="Sandbox capacity" hint="" period={PERIOD} />);

    expect(await screen.findByText("1 open")).toBeInTheDocument();
  });

  it("warns by colour as well as by number as a host fills up", async () => {
    deployment(
      {
        connection: connection({ id: "calm", name: "Calm" }),
        listing: { sessions: [session()], tenant_limit: 8 },
      },
      {
        connection: connection({ id: "busy", name: "Busy", is_default: false }),
        listing: { sessions: [session(), session(), session()], tenant_limit: 4 },
      },
      {
        connection: connection({ id: "full", name: "Full", is_default: false }),
        listing: { sessions: [session(), session(), session(), session()], tenant_limit: 4 },
      },
    );

    const { container } = render(
      <SandboxCapacityWidget title="Sandbox capacity" hint="" period={PERIOD} />,
    );

    await screen.findByText("1 of 8");
    await waitFor(() => expect(tracks(container)).toHaveLength(3));
    const [calm, busy, full] = tracks(container);
    expect(calm).toContain("bg-chart");
    expect(busy).toContain("bg-warning");
    expect(full).toContain("bg-destructive");
  });

  it("says a host is unreachable instead of reporting it as idle", async () => {
    deployment({
      connection: connection({ name: "sandboxd-eu" }),
      fails: "The sandbox service did not answer: connection refused",
    });

    render(<SandboxCapacityWidget title="Sandbox capacity" hint="" period={PERIOD} />);

    expect(await screen.findByText(/connection refused/)).toBeInTheDocument();
    // The failure that #129 calls an empty view and a dead host being the same
    // pixels: a card reading "0 open" for a host nobody can reach.
    expect(screen.queryByText("0 open")).not.toBeInTheDocument();
  });

  it("tells a Daytona connection apart from an idle host, and asks it nothing", async () => {
    deployment({ connection: connection({ kind: "daytona", base_url: null }) });

    render(<SandboxCapacityWidget title="Sandbox capacity" hint="" period={PERIOD} />);

    expect(await screen.findByText(/counted in that account/)).toBeInTheDocument();
    expect(sessionsAskedFor()).toEqual([]);
  });

  it("leaves out a connection no agent can reach any more", async () => {
    deployment(
      { connection: connection({ id: "live", name: "Live" }), listing: { sessions: [session()] } },
      { connection: connection({ id: "gone", name: "Retired", is_active: false }) },
    );

    render(<SandboxCapacityWidget title="Sandbox capacity" hint="" period={PERIOD} />);

    await screen.findByText("Live");
    expect(screen.queryByText("Retired")).not.toBeInTheDocument();
    expect(sessionsAskedFor()).toEqual(["live"]);
  });

  it("says no host is registered rather than showing an empty list", async () => {
    deployment();

    render(<SandboxCapacityWidget title="Sandbox capacity" hint="" period={PERIOD} />);

    expect(await screen.findByText("No sandbox host registered")).toBeInTheDocument();
  });

  it("says the listing failed, and asks again when told to", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(502, "Bad Gateway"));

    render(<SandboxCapacityWidget title="Sandbox capacity" hint="" period={PERIOD} />);

    expect(await screen.findByText("Couldn't load this")).toBeInTheDocument();
    expect(screen.queryByText("No sandbox host registered")).not.toBeInTheDocument();

    deployment({ connection: connection({ name: "Back up" }), listing: { sessions: [session()] } });
    screen.getByRole("button", { name: "Retry" }).click();

    expect(await screen.findByText("Back up")).toBeInTheDocument();
  });
});

describe("the open-sandboxes card", () => {
  function card() {
    return <SandboxSessionsWidget title="Open sandboxes" hint="" period={PERIOD} />;
  }

  it("names the agent, what shares the sandbox, its runtime, state and idle time", async () => {
    deployment({
      connection: connection({ name: "sandboxd-eu" }),
      listing: { sessions: [session()] },
    });

    render(card());

    expect(await screen.findByText("Support triage")).toBeInTheDocument();
    expect(screen.getByText("shared in one conversation")).toBeInTheDocument();
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("12s idle")).toBeInTheDocument();
    expect(screen.getByText("on sandboxd-eu")).toBeInTheDocument();
  });

  it("does not sample memory on load, and does once asked", async () => {
    // The whole reason usage is a switch: the service pays a daemon round trip
    // per sandbox for it, and this listing refetches every ten seconds.
    deployment({
      connection: connection(),
      listing: {
        sessions: [
          session({
            usage: { memory_bytes: 64 * 1024 * 1024, memory_limit_bytes: 512 * 1024 * 1024 },
          }),
        ],
      },
    });

    render(card());
    await screen.findByText("Support triage");
    expect(sampledUsage()).toEqual([]);
    expect(screen.queryByText("64.0 MB of 512.0 MB")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("switch"));

    expect(await screen.findByText("64.0 MB of 512.0 MB")).toBeInTheDocument();
    expect(sampledUsage().length).toBeGreaterThan(0);
  });

  it("reads memory alone when the host set that sandbox no ceiling", async () => {
    deployment({
      connection: connection(),
      listing: { sessions: [session({ usage: { memory_bytes: 2048, memory_limit_bytes: null } })] },
    });

    render(card());
    await screen.findByText("Support triage");
    await userEvent.click(screen.getByRole("switch"));

    expect(await screen.findByText("2.0 KB")).toBeInTheDocument();
  });

  it("says no agent was recorded for a run-scoped sandbox rather than guessing one", async () => {
    // A `run` scope has no `agent_workspaces` row by design, so there is nothing
    // to have joined - and the session id is not decoded to invent one.
    deployment({
      connection: connection(),
      listing: { sessions: [session({ agent_id: null, conversation_id: null, scope: null })] },
    });

    render(card());

    expect(await screen.findByText("No agent recorded")).toBeInTheDocument();
    expect(screen.getByText("one run only")).toBeInTheDocument();
  });

  it("says no agent was recorded when the row points at one this caller cannot read", async () => {
    agentRows = [];
    deployment({ connection: connection(), listing: { sessions: [session()] } });

    render(card());

    expect(await screen.findByText("No agent recorded")).toBeInTheDocument();
  });

  it("shows a hibernated sandbox as itself - stopped to free a slot, not gone", async () => {
    deployment({
      connection: connection(),
      listing: { sessions: [session({ alive: false, state: "hibernated" })] },
    });

    render(card());

    expect(await screen.findByText("hibernated")).toBeInTheDocument();
  });

  it.each([
    [90, "2m idle"],
    [7_200, "2h idle"],
  ])("reads %ss of idleness as %s", async (idle_seconds, expected) => {
    deployment({ connection: connection(), listing: { sessions: [session({ idle_seconds })] } });

    render(card());

    expect(await screen.findByText(expected)).toBeInTheDocument();
  });

  it("opens one sandbox's activity log, and closes it again", async () => {
    deployment({
      connection: connection(),
      listing: { sessions: [session({ session_id: "cc-1" })] },
      logs: { "cc-1": [event({ target: "/workspace/report.py" })] },
    });

    render(card());
    await userEvent.click(await screen.findByRole("button", { name: /Show what was done/ }));

    expect(await screen.findByText("/workspace/report.py")).toBeInTheDocument();
    expect(screen.getByText("write_file")).toBeInTheDocument();
    expect(screen.getByText("18ms")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Show what was done/ }));

    expect(screen.queryByText("/workspace/report.py")).not.toBeInTheDocument();
  });

  it("marks an operation that failed inside the sandbox", async () => {
    deployment({
      connection: connection(),
      listing: { sessions: [session({ session_id: "cc-1" })] },
      logs: { "cc-1": [event({ seq: 1 }), event({ seq: 2, op: "run", ok: false })] },
    });

    const { container } = render(card());
    await userEvent.click(await screen.findByRole("button", { name: /Show what was done/ }));
    await screen.findByText("run");

    const failed = container.querySelectorAll("li.text-destructive");
    expect(failed).toHaveLength(1);
  });

  it("says a log that could not be read failed, rather than showing it as empty", async () => {
    deployment({
      connection: connection(),
      listing: { sessions: [session({ session_id: "cc-1" })] },
      logs: { "cc-1": "That activity log could not be read: 502" },
    });

    render(card());
    await userEvent.click(await screen.findByRole("button", { name: /Show what was done/ }));

    expect(await screen.findByText(/could not be read/)).toBeInTheDocument();
    expect(screen.queryByText("Nothing recorded for this sandbox yet.")).not.toBeInTheDocument();
  });

  it("says nothing has been recorded for a sandbox that has done nothing", async () => {
    deployment({
      connection: connection(),
      listing: { sessions: [session({ session_id: "cc-1" })] },
    });

    render(card());
    await userEvent.click(await screen.findByRole("button", { name: /Show what was done/ }));

    expect(await screen.findByText("Nothing recorded for this sandbox yet.")).toBeInTheDocument();
  });

  it("says the host is unreachable instead of saying nothing is running", async () => {
    deployment({
      connection: connection(),
      fails: "The sandbox service did not answer: connection refused",
    });

    render(card());

    expect(await screen.findByText(/connection refused/)).toBeInTheDocument();
    expect(
      screen.queryByText("Nothing is running. A sandbox opens the first time an agent runs code."),
    ).not.toBeInTheDocument();
  });

  it("says nothing is running when the host answers with an empty listing", async () => {
    deployment({ connection: connection() });

    render(card());

    expect(
      await screen.findByText(
        "Nothing is running. A sandbox opens the first time an agent runs code.",
      ),
    ).toBeInTheDocument();
  });

  it("reads only the default host, since capacity is the card covering them all", async () => {
    deployment(
      { connection: connection({ id: "other", name: "Other", is_default: false }) },
      {
        connection: connection({ id: "chosen", name: "Chosen", is_default: true }),
        listing: { sessions: [session()] },
      },
    );

    render(card());

    await screen.findByText("Support triage");
    expect(sessionsAskedFor()).toEqual(["chosen"]);
  });

  it("says a Daytona host keeps its sessions elsewhere, and asks it nothing", async () => {
    deployment({ connection: connection({ kind: "daytona", base_url: null }) });

    render(card());

    expect(await screen.findByText("Sandboxes run on Daytona")).toBeInTheDocument();
    expect(sessionsAskedFor()).toEqual([]);
  });

  it("says no host is registered rather than listing nothing", async () => {
    deployment();

    render(card());

    expect(await screen.findByText("No sandbox host registered")).toBeInTheDocument();
  });

  it("says the connection listing failed, and asks again when told to", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(502, "Bad Gateway"));

    render(card());

    expect(await screen.findByText("Couldn't load this")).toBeInTheDocument();

    deployment({ connection: connection(), listing: { sessions: [session()] } });
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Support triage")).toBeInTheDocument();
  });
});

describe("the sandbox runtimes card", () => {
  function card() {
    return <SandboxPolicyWidget title="Sandbox runtimes" hint="" period={PERIOD} />;
  }

  it("names the host's ceilings as ceilings, never as a fraction", async () => {
    // This is where `max_sessions` and `max_open_sessions` belong: they are the
    // whole host's, so there is no count of ours to divide them by.
    deployment({
      connection: connection(),
      allows: {
        runtimes: [runtime()],
        max_sessions_per_tenant: 8,
        max_sessions: 40,
        max_open_sessions: 20,
      },
    });

    render(card());

    expect(await screen.findByText("Resident, host-wide")).toBeInTheDocument();
    expect(screen.getByText("Open, host-wide")).toBeInTheDocument();
    expect(screen.getByText("This organization")).toBeInTheDocument();
    expect(screen.getByText("40")).toBeInTheDocument();
    expect(screen.queryByText("0 of 40")).not.toBeInTheDocument();
  });

  it("names only the ceilings the service publishes", async () => {
    deployment({ connection: connection(), allows: { runtimes: [runtime()] } });

    render(card());

    await screen.findByText("python");
    expect(screen.queryByText("Resident, host-wide")).not.toBeInTheDocument();
    expect(screen.queryByText("This organization")).not.toBeInTheDocument();
  });

  it("lists each allowed runtime with the memory ceiling behind it", async () => {
    deployment({
      connection: connection(),
      allows: {
        runtimes: [runtime(), runtime({ alias: "node", mem_limit: "1g" })],
        default_runtime: "python",
      },
    });

    render(card());

    expect(await screen.findByText("python")).toBeInTheDocument();
    expect(screen.getByText("512m")).toBeInTheDocument();
    expect(screen.getByText("node")).toBeInTheDocument();
    expect(screen.getByText("1g")).toBeInTheDocument();
    expect(screen.getByText("default")).toBeInTheDocument();
  });

  it("says a runtime the host caps nothing on has no ceiling", async () => {
    deployment({ connection: connection(), allows: { runtimes: [runtime({ mem_limit: null })] } });

    render(card());

    expect(await screen.findByText("no ceiling")).toBeInTheDocument();
  });

  it("treats a service allowing no runtime as a fault, not as an empty card", async () => {
    // Nothing can run code on it at all, which is not the same news as "no
    // sandbox host is registered".
    deployment({ connection: connection(), allows: { runtimes: [] } });

    render(card());

    expect(
      await screen.findByText("This service allows no runtime, so no agent can run code on it."),
    ).toBeInTheDocument();
    expect(screen.queryByText("No sandbox host registered")).not.toBeInTheDocument();
  });

  it("says the allowlist could not be read, and asks the host again when told to", async () => {
    // Nothing polls this one, so the Retry is the only way back - which is why
    // `useSandboxPolicy` exposes a refetch at all.
    deployment({ connection: connection(), allows: "The sandbox service did not answer" });

    render(card());
    expect(await screen.findByText("Couldn't load this")).toBeInTheDocument();

    deployment({ connection: connection(), allows: { runtimes: [runtime({ alias: "ruby" })] } });
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("ruby")).toBeInTheDocument();
  });

  it("does not ask Daytona for an allowlist it does not publish", async () => {
    deployment({ connection: connection({ kind: "daytona", base_url: null }) });

    render(card());

    expect(await screen.findByText("Sandboxes run on Daytona")).toBeInTheDocument();
    expect(policiesAskedFor()).toEqual([]);
  });

  it("says no host is registered rather than showing an empty allowlist", async () => {
    deployment();

    render(card());

    expect(await screen.findByText("No sandbox host registered")).toBeInTheDocument();
    expect(policiesAskedFor()).toEqual([]);
  });

  it("says the connection listing failed rather than blaming the host", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(502, "Bad Gateway"));

    render(card());

    expect(await screen.findByText("Couldn't load this")).toBeInTheDocument();
    expect(screen.queryByText("No sandbox host registered")).not.toBeInTheDocument();

    deployment({ connection: connection(), allows: { runtimes: [runtime({ alias: "go" })] } });
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("go")).toBeInTheDocument();
  });
});
