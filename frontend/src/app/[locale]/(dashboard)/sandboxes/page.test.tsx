import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SandboxesPage from "./page";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";

/**
 * The page's half of #140: two tabs on two clocks. Connections is
 * configuration; Running is live and polls — so the panel that polls must not
 * even be mounted while its tab is hidden, which is what `sessionsAsked`
 * pins below.
 */

const state = vi.hoisted(() => ({
  connections: [] as SandboxConnectionRecord[],
  isLoading: false,
  error: null as string | null,
  canManage: true,
  urlParams: new URLSearchParams(),
  sessionsAsked: [] as (string | null)[],
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => state.urlParams,
  usePathname: () => "/sandboxes",
  useParams: () => ({}),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

vi.mock("@/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks")>()),
  usePermissions: () => ({
    can: () => state.canManage,
    isLoading: false,
  }),
  useSandboxConnections: () => ({
    connections: state.connections,
    isLoading: state.isLoading,
    error: state.error,
    refresh: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  }),
  useSandboxSessions: (id: string | null) => {
    state.sessionsAsked.push(id);
    return { listing: null, isLoading: false, error: null };
  },
  useSandboxEvents: () => ({ log: null, isLoading: false, error: null }),
  useSandboxPolicy: () => ({ policy: null, isLoading: false, error: null, refetch: vi.fn() }),
  // The sessions panel names the agent that opened each sandbox, and the real hook
  // reaches for a query client this page's spec does not provide.
  useAgents: () => ({ agents: [], isLoading: false, error: null }),
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

beforeEach(() => {
  state.connections = [connection()];
  state.isLoading = false;
  state.error = null;
  state.canManage = true;
  state.urlParams = new URLSearchParams();
  state.sessionsAsked = [];
  window.history.replaceState({}, "", "/sandboxes");
});

describe("the sandboxes page", () => {
  it("opens on connections, with the live panel not even mounted", () => {
    render(<SandboxesPage />);

    expect(screen.getByRole("tab", { name: "Connections", selected: true })).toBeVisible();
    expect(screen.getByText("Local Docker")).toBeVisible();
    // Unmounted, not merely hidden: a mounted panel would poll a page nobody
    // is reading, every ten seconds.
    expect(state.sessionsAsked).toEqual([]);
  });

  it("mounts the live panel only when its tab is opened, and records the tab in the URL", async () => {
    render(<SandboxesPage />);

    await userEvent.click(screen.getByRole("tab", { name: "Running" }));

    expect(screen.getByText("Running on Local Docker")).toBeVisible();
    expect(state.sessionsAsked).toContain("c-1");
    expect(window.location.search).toBe("?tab=running");

    await userEvent.click(screen.getByRole("tab", { name: "Connections" }));
    // The default tab keeps the parameter off, so /sandboxes stays one URL.
    expect(window.location.search).toBe("");
  });

  it("lands on the running tab from a pasted link", () => {
    state.urlParams = new URLSearchParams("tab=running");
    render(<SandboxesPage />);

    expect(screen.getByRole("tab", { name: "Running", selected: true })).toBeVisible();
    expect(screen.getByText("Running on Local Docker")).toBeVisible();
  });

  it("offers the running tab only container hosts, never Daytona", async () => {
    state.connections = [
      connection({ id: "c-1", name: "Docker A", is_default: true }),
      connection({ id: "c-2", name: "Daytona", kind: "daytona", is_default: false }),
      connection({ id: "c-3", name: "Switched off", is_active: false, is_default: false }),
    ];
    render(<SandboxesPage />);

    await userEvent.click(screen.getByRole("tab", { name: "Running" }));

    // One watchable host: named, no selector needed.
    expect(screen.getByText("Running on Docker A")).toBeVisible();
    expect(screen.queryByRole("combobox", { name: "Host" })).toBeNull();
  });

  it("explains an empty running tab instead of opening onto nothing", async () => {
    state.connections = [connection({ kind: "daytona" })];
    render(<SandboxesPage />);

    await userEvent.click(screen.getByRole("tab", { name: "Running" }));

    expect(screen.getByText("No container connection registered")).toBeVisible();
  });

  it("draws one header and a skeleton while connections load", () => {
    state.isLoading = true;
    render(<SandboxesPage />);

    // The loading branch used to render a second copy of the whole header.
    expect(screen.getAllByText("Sandboxes")).toHaveLength(1);
    expect(screen.queryByText("Local Docker")).toBeNull();
  });

  it("shows the refusal where the rows would be, not an empty collection", () => {
    state.error = "Failed to load sandbox connections";
    render(<SandboxesPage />);

    expect(screen.getByText("Failed to load sandbox connections")).toBeVisible();
    expect(screen.queryByText(/No sandbox connections yet/)).toBeNull();
  });

  it("shows the refusal on the running tab too, never a false empty state", async () => {
    state.error = "Failed to load sandbox connections";
    state.connections = [];
    render(<SandboxesPage />);

    await userEvent.click(screen.getByRole("tab", { name: "Running" }));

    // "No container connection registered" would state as fact something the
    // request never answered — hosts may be registered and running things.
    expect(screen.getByText("Failed to load sandbox connections")).toBeVisible();
    expect(screen.queryByText("No container connection registered")).toBeNull();
  });

  it("hides the add button from a caller who may not manage connections", () => {
    state.canManage = false;
    render(<SandboxesPage />);

    expect(screen.queryByRole("button", { name: /Add connection/ })).toBeNull();
  });
});
