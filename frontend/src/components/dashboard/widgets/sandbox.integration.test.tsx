import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as renderBare, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SandboxCapacityWidget } from "./sandbox-capacity";
import { ApiError, apiClient } from "@/lib/api-client";
import type { Period } from "@/lib/dashboard/period";
import type {
  SandboxConnectionRecord,
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

interface HostFixture {
  connection: SandboxConnectionRecord;
  listing?: Partial<SandboxSessionList>;
  /** The sentence a host answers with instead of a listing. */
  fails?: string;
}

/** A deployment's registered hosts, each answering for itself. */
function deployment(...hosts: HostFixture[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/sandbox-connections") {
      return { items: hosts.map((host) => host.connection), total: hosts.length };
    }
    const asked = /^\/sandbox-connections\/([^/]+)\/sessions/.exec(path);
    if (asked !== null) {
      const host = hosts.find((candidate) => candidate.connection.id === asked[1]);
      if (host?.fails !== undefined) throw new ApiError(502, host.fails);
      return {
        sessions: [],
        limit: null,
        open_limit: null,
        tenant_limit: null,
        ...host?.listing,
      };
    }
    throw new ApiError(404, `nothing serves ${path}`);
  });
}

/** Which hosts the card actually asked about. */
function sessionsAskedFor(): string[] {
  return vi
    .mocked(apiClient.get)
    .mock.calls.map(([path]) => /^\/sandbox-connections\/([^/]+)\/sessions/.exec(path)?.[1])
    .filter((id): id is string => id !== undefined);
}

function tracks(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("[style*='width']")).map(
    (element) => element.className,
  );
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
});

describe("the sandbox capacity card", () => {
  it("counts this organization's sandboxes against the ceiling that applies to it", async () => {
    deployment({
      connection: connection({ name: "sandboxd-eu" }),
      listing: { sessions: [session(), session(), session()], tenant_limit: 8 },
    });

    render(<SandboxCapacityWidget title="Sandbox capacity" period={PERIOD} />);

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
      <SandboxCapacityWidget title="Sandbox capacity" period={PERIOD} />,
    );

    expect(await screen.findByText("2 open")).toBeInTheDocument();
    expect(screen.queryByText("2 of 40")).not.toBeInTheDocument();
    expect(screen.queryByText("2 of 20")).not.toBeInTheDocument();
    // And no bar either: a track needs a denominator this response cannot give.
    expect(tracks(container)).toEqual([]);
  });

  it("says one sandbox is open rather than building the plural from English", async () => {
    deployment({ connection: connection(), listing: { sessions: [session()] } });

    render(<SandboxCapacityWidget title="Sandbox capacity" period={PERIOD} />);

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
      <SandboxCapacityWidget title="Sandbox capacity" period={PERIOD} />,
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

    render(<SandboxCapacityWidget title="Sandbox capacity" period={PERIOD} />);

    expect(await screen.findByText(/connection refused/)).toBeInTheDocument();
    // The failure that #129 calls an empty view and a dead host being the same
    // pixels: a card reading "0 open" for a host nobody can reach.
    expect(screen.queryByText("0 open")).not.toBeInTheDocument();
  });

  it("tells a Daytona connection apart from an idle host, and asks it nothing", async () => {
    deployment({ connection: connection({ kind: "daytona", base_url: null }) });

    render(<SandboxCapacityWidget title="Sandbox capacity" period={PERIOD} />);

    expect(await screen.findByText(/counted in that account/)).toBeInTheDocument();
    expect(sessionsAskedFor()).toEqual([]);
  });

  it("leaves out a connection no agent can reach any more", async () => {
    deployment(
      { connection: connection({ id: "live", name: "Live" }), listing: { sessions: [session()] } },
      { connection: connection({ id: "gone", name: "Retired", is_active: false }) },
    );

    render(<SandboxCapacityWidget title="Sandbox capacity" period={PERIOD} />);

    await screen.findByText("Live");
    expect(screen.queryByText("Retired")).not.toBeInTheDocument();
    expect(sessionsAskedFor()).toEqual(["live"]);
  });

  it("says no host is registered rather than showing an empty list", async () => {
    deployment();

    render(<SandboxCapacityWidget title="Sandbox capacity" period={PERIOD} />);

    expect(await screen.findByText("No sandbox host registered")).toBeInTheDocument();
  });

  it("says the listing failed, and asks again when told to", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(502, "Bad Gateway"));

    render(<SandboxCapacityWidget title="Sandbox capacity" period={PERIOD} />);

    expect(await screen.findByText("Couldn't load this")).toBeInTheDocument();
    expect(screen.queryByText("No sandbox host registered")).not.toBeInTheDocument();

    deployment({ connection: connection({ name: "Back up" }), listing: { sessions: [session()] } });
    screen.getByRole("button", { name: "Retry" }).click();

    expect(await screen.findByText("Back up")).toBeInTheDocument();
  });
});
