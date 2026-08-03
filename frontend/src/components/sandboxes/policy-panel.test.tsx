import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PolicyPanel } from "./policy-panel";
import type { SandboxConnectionRecord, SandboxPolicy } from "@/lib/sandbox-connections-api";

const state = vi.hoisted(() => ({
  policy: null as SandboxPolicy | null,
  isLoading: false,
  error: null as string | null,
  asked: [] as (string | null)[],
}));

vi.mock("@/hooks", () => ({
  useSandboxPolicy: (id: string | null) => {
    state.asked.push(id);
    return { policy: state.policy, isLoading: state.isLoading, error: state.error };
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

function policy(overrides: Partial<SandboxPolicy> = {}): SandboxPolicy {
  return {
    kind: "docker",
    runtimes: [
      {
        alias: "python",
        image: "python:3.12-slim",
        description: "Python and the standard library.",
        builds: false,
        mem_limit: "512m",
        cpus: 1,
        network_mode: "none",
      },
    ],
    default_runtime: "python",
    max_sessions: null,
    max_open_sessions: null,
    max_sessions_per_tenant: 5,
    idle_timeout: 900,
    workspace_root: null,
    persist_containers: true,
    ...overrides,
  };
}

beforeEach(() => {
  state.policy = policy();
  state.isLoading = false;
  state.error = null;
  state.asked = [];
});

describe("PolicyPanel", () => {
  it("asks nothing while it is closed", () => {
    render(<PolicyPanel connection={null} onOpenChange={vi.fn()} />);

    expect(state.asked).toEqual([null]);
  });

  it("shows what the service allows, with the ceilings behind each alias", () => {
    // An operator whose agents keep hitting a memory limit has somewhere to look.
    render(<PolicyPanel connection={connection()} onOpenChange={vi.fn()} />);

    expect(screen.getByText("python")).toBeVisible();
    expect(screen.getByText("python:3.12-slim")).toBeVisible();
    expect(screen.getByText("512m")).toBeVisible();
    expect(screen.getByText("Default")).toBeVisible();
  });

  it("says only changeable there, because a browser must not reconfigure the socket", () => {
    render(<PolicyPanel connection={connection()} onOpenChange={vi.fn()} />);

    expect(screen.getByText(/only changeable there/i)).toBeVisible();
  });

  it("renders the per-tenant ceiling and the idle timeout in minutes", () => {
    render(<PolicyPanel connection={connection()} onOpenChange={vi.fn()} />);

    expect(screen.getByText("5")).toBeVisible();
    expect(screen.getByText("15 min")).toBeVisible();
  });

  it("prints a timeout that is not whole minutes in seconds", () => {
    state.policy = policy({ idle_timeout: 90 });
    render(<PolicyPanel connection={connection()} onOpenChange={vi.fn()} />);

    expect(screen.getByText("90s")).toBeVisible();
  });

  it("says nothing rather than zero for a ceiling the service did not report", () => {
    state.policy = policy({ max_sessions_per_tenant: null, idle_timeout: null });
    render(<PolicyPanel connection={connection()} onOpenChange={vi.fn()} />);

    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("names a runtime the service builds rather than pulls", () => {
    state.policy = policy({
      runtimes: [
        {
          alias: "custom",
          image: null,
          description: "",
          builds: true,
          mem_limit: null,
          cpus: null,
          network_mode: null,
        },
      ],
    });
    render(<PolicyPanel connection={connection()} onOpenChange={vi.fn()} />);

    expect(screen.getByText("built on this host")).toBeVisible();
  });

  it("says an empty allowlist means no sandbox can start", () => {
    // It answers, it accepts the token, and it can do nothing.
    state.policy = policy({ runtimes: [] });
    render(<PolicyPanel connection={connection()} onOpenChange={vi.fn()} />);

    expect(screen.getByText(/allows no runtime/i)).toBeVisible();
  });

  it("reports a service that did not answer, and what it costs", () => {
    state.policy = null;
    state.error = "The sandbox service at http://sandboxd:8080 did not answer";
    render(<PolicyPanel connection={connection()} onOpenChange={vi.fn()} />);

    expect(screen.getByText(/fails on its first tool call/)).toBeVisible();
  });

  it("draws a placeholder while the service is being asked", () => {
    state.policy = null;
    state.isLoading = true;
    // `document`, not the render container: the dialog draws in a portal.
    render(<PolicyPanel connection={connection()} onOpenChange={vi.fn()} />);

    expect(document.querySelector(".h-32")).not.toBeNull();
  });
});
