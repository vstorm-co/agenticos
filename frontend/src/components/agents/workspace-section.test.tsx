import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceSection } from "./workspace-section";
import type { SandboxConnectionRecord, SandboxPolicy } from "@/lib/sandbox-connections-api";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

const state = vi.hoisted(() => ({
  connections: [] as SandboxConnectionRecord[],
  connectionsError: null as string | null,
  policy: null as SandboxPolicy | null,
  policyError: null as string | null,
  policyLoading: false,
}));

vi.mock("@/hooks", () => ({
  useSandboxConnections: () => ({
    connections: state.connections,
    isLoading: false,
    error: state.connectionsError,
    refresh: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  }),
  useSandboxPolicy: () => ({
    policy: state.policy,
    isLoading: state.policyLoading,
    error: state.policyError,
  }),
}));

const SANDBOX: CapabilityCatalogEntry = {
  id: "sandbox",
  name: "Files & shell",
  category: "analysis",
  description: "Read, write and run things in a workspace that persists between turns.",
  side_effecting: true,
  scopes: ["sandbox:execute"],
  tools: [
    { id: "read_file", name: "read_file", description: "Read a file from the workspace." },
    { id: "execute", name: "execute", description: "Run a shell command in the workspace." },
  ],
  config_schema: {
    type: "object",
    properties: {
      backend: { type: "string", enum: ["state", "service"], default: "state" },
    },
  },
  contracts: [],
  requires_secret: null,
};

function connection(overrides: Partial<SandboxConnectionRecord> = {}): SandboxConnectionRecord {
  return {
    id: "c1",
    name: "Local Docker",
    kind: "docker",
    base_url: "http://sandboxd:8080",
    secret_id: "s1",
    default_runtime: null,
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

function binding(config: Record<string, unknown> = {}): CapabilityBindingSpec {
  return {
    id: "sandbox",
    config,
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
    enabled: true,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  state.connections = [connection()];
  state.connectionsError = null;
  state.policy = policy();
  state.policyError = null;
  state.policyLoading = false;
});

describe("WorkspaceSection", () => {
  it("renders nothing when the deployment did not register the capability", () => {
    // An empty section reads as something that failed to load.
    const { container } = render(
      <WorkspaceSection definition={undefined} binding={undefined} onChange={vi.fn()} />,
      { wrapper },
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("shows the backend the binding is set to, defaulting to Files", () => {
    render(<WorkspaceSection definition={SANDBOX} binding={binding()} onChange={vi.fn()} />, {
      wrapper,
    });

    expect(screen.getByRole("button", { name: /^Files/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("choosing a backend writes it to the binding", async () => {
    // There is no None tile: turning the capability off is the switch above,
    // the same one every capability has, and a second control for one decision
    // is two controls that disagree.
    const onChange = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state" })}
        onChange={onChange}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByRole("button", { name: /^Container/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ backend: "service" }) }),
    );
  });

  it("warns that a shared workspace is shared, because a schema cannot", () => {
    // The one setting here that lets one person read another's files. It ships
    // without a permission of its own, so the consequence is made visible.
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state", session_scope: "agent" })}
        onChange={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.getByText(/visible to the rest of the organization/i)).toBeVisible();
  });

  it("says nothing alarming about a workspace nobody else can read", () => {
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state", session_scope: "conversation" })}
        onChange={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.queryByText(/visible to the rest of the organization/i)).toBeNull();
  });

  it("offers a host and a runtime only where there is a container to run them in", () => {
    const { rerender } = render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state" })}
        onChange={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.queryByLabelText("Runtime")).toBeNull();
    expect(screen.queryByLabelText("Runs on")).toBeNull();

    rerender(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "service" })}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Runtime")).toBeVisible();
    expect(screen.getByLabelText("Runs on")).toBeVisible();
  });

  it("clears the host and the runtime when moving to a backend that runs neither", async () => {
    // Publish refuses both combinations, so leaving them behind would fail in a
    // form somebody has already left.
    const onChange = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "service", runtime: "python", connection_id: "c1" })}
        onChange={onChange}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByRole("button", { name: /^Files/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ backend: "state", runtime: null, connection_id: null }),
      }),
    );
  });

  it("cannot offer a shell on the backend that has none", () => {
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state" })}
        onChange={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.getByLabelText("Allow shell commands")).toBeDisabled();
    expect(screen.getByText(/pair it with Run Python/i)).toBeVisible();
  });

  it("does not render the generated form as well as the choice", () => {
    // The schema would draw the same fields a second time.
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "service" })}
        onChange={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.queryByLabelText("backend")).toBeNull();
  });

  it("changing who shares it is written to the binding", async () => {
    const onChange = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state", session_scope: "conversation" })}
        onChange={onChange}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Who shares it by default" }));
    await userEvent.click(screen.getByRole("option", { name: "Everyone using this agent" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ session_scope: "agent" }) }),
    );
  });

  it("offers the channel scope a messaging surface needs", async () => {
    // `conversation` on Slack is one workspace per thread, which is fifty
    // containers in a busy channel.
    const onChange = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state" })}
        onChange={onChange}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Who shares it by default" }));
    await userEvent.click(screen.getByRole("option", { name: "This channel" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ session_scope: "channel" }) }),
    );
  });

  describe("the host it runs on", () => {
    it("defaults to whichever the organization made default", () => {
      render(
        <WorkspaceSection
          definition={SANDBOX}
          binding={binding({ backend: "service" })}
          onChange={vi.fn()}
        />,
        { wrapper },
      );

      expect(screen.getByLabelText("Runs on")).toHaveTextContent("Whichever is default");
    });

    it("pinning one writes its id and drops the old runtime", async () => {
      // A runtime is an alias one service allows; carrying it to another host is
      // how an agent asks for an image that host has never heard of.
      state.connections = [connection(), connection({ id: "c2", name: "Big box" })];
      const onChange = vi.fn();
      render(
        <WorkspaceSection
          definition={SANDBOX}
          binding={binding({ backend: "service", runtime: "python" })}
          onChange={onChange}
        />,
        { wrapper },
      );

      await userEvent.click(screen.getByRole("combobox", { name: "Runs on" }));
      await userEvent.click(screen.getByRole("option", { name: "Big box" }));

      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({
          config: expect.objectContaining({ connection_id: "c2", runtime: null }),
        }),
      );
    });

    it("says an organization has none rather than offering an empty list", () => {
      // Publishing is refused for it, and being told here beats a publish error.
      state.connections = [];
      render(
        <WorkspaceSection
          definition={SANDBOX}
          binding={binding({ backend: "service" })}
          onChange={vi.fn()}
        />,
        { wrapper },
      );

      expect(screen.getByText(/registered no sandbox connection/i)).toBeVisible();
      expect(screen.getByLabelText("Runs on")).toBeDisabled();
    });

    it("does not offer a host that was switched off", async () => {
      state.connections = [
        connection(),
        connection({ id: "c2", name: "Retired", is_active: false }),
      ];
      render(
        <WorkspaceSection
          definition={SANDBOX}
          binding={binding({ backend: "service" })}
          onChange={vi.fn()}
        />,
        { wrapper },
      );

      await userEvent.click(screen.getByRole("combobox", { name: "Runs on" }));

      expect(screen.queryByRole("option", { name: "Retired" })).toBeNull();
    });
  });

  describe("the runtime", () => {
    it("offers what the service allows rather than free text", async () => {
      // Free text is a promise nothing keeps: an alias the service does not know
      // is accepted, published, and refused on the first tool call.
      const onChange = vi.fn();
      render(
        <WorkspaceSection
          definition={SANDBOX}
          binding={binding({ backend: "service" })}
          onChange={onChange}
        />,
        { wrapper },
      );

      await userEvent.click(screen.getByRole("combobox", { name: "Runtime" }));
      await userEvent.click(screen.getByRole("option", { name: /python/ }));

      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ config: expect.objectContaining({ runtime: "python" }) }),
      );
    });

    it("choosing the default clears the alias rather than storing an empty one", async () => {
      const onChange = vi.fn();
      render(
        <WorkspaceSection
          definition={SANDBOX}
          binding={binding({ backend: "service", runtime: "python" })}
          onChange={onChange}
        />,
        { wrapper },
      );

      await userEvent.click(screen.getByRole("combobox", { name: "Runtime" }));
      await userEvent.click(screen.getByRole("option", { name: /service's own default/i }));

      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ config: expect.objectContaining({ runtime: null }) }),
      );
    });

    it("keeps a runtime's memory cap in the list and off the closed trigger", async () => {
      // The cap is how one runtime is weighed against another. Radix draws the
      // selected item's `ItemText` in the trigger, so in `children` it followed
      // the choice out and sat there as a bare number with nothing to compare.
      render(
        <WorkspaceSection
          definition={SANDBOX}
          binding={binding({ backend: "service", runtime: "python" })}
          onChange={vi.fn()}
        />,
        { wrapper },
      );

      // `not.toHaveTextContent`, not `queryByText`: the cap used to be a text
      // node glued to the alias, which `queryByText("512m")` would not have
      // matched - and a regression test that passes against the bug is worse
      // than none.
      const picker = screen.getByRole("combobox", { name: "Runtime" });
      expect(picker).toHaveTextContent("python");
      expect(picker).not.toHaveTextContent("512m");

      await userEvent.click(picker);
      const chosen = await screen.findByRole("option", { name: "python" });
      expect(within(chosen).getByText("512m")).toBeVisible();
    });

    it("names an alias the connection no longer allows", () => {
      // Otherwise a spec that was valid keeps looking valid while the agent
      // fails on its first tool call.
      render(
        <WorkspaceSection
          definition={SANDBOX}
          binding={binding({ backend: "service", runtime: "data-science" })}
          onChange={vi.fn()}
        />,
        { wrapper },
      );

      expect(screen.getByText(/no longer allows/i)).toBeVisible();
    });

    it("reports a service that did not answer instead of an empty allowlist", () => {
      // "No runtimes" and "no answer" are different problems and only one of
      // them is the author's.
      state.policy = null;
      state.policyError = "The sandbox service at http://sandboxd:8080 did not answer";
      render(
        <WorkspaceSection
          definition={SANDBOX}
          binding={binding({ backend: "service" })}
          onChange={vi.fn()}
        />,
        { wrapper },
      );

      expect(screen.getByText(/did not answer/i)).toBeVisible();
      expect(screen.getByLabelText("Runtime")).toBeDisabled();
    });
  });

  it("the shell can be removed from a backend that has one", async () => {
    const onChange = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "service" })}
        onChange={onChange}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByLabelText("Allow shell commands"));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ include_execute: false }) }),
    );
  });

  it("a choice made before the binding exists cannot write to nothing", async () => {
    // The row's switch creates the binding; until it does there is nothing to
    // patch, and patching `undefined` would throw where a user clicked.
    const onChange = vi.fn();
    render(<WorkspaceSection definition={SANDBOX} binding={undefined} onChange={onChange} />, {
      wrapper,
    });

    await userEvent.click(screen.getByRole("button", { name: /^Container/ }));

    expect(onChange).not.toHaveBeenCalled();
  });

  it("is inert for somebody who may not edit the agent", () => {
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "service" })}
        onChange={vi.fn()}
        disabled
      />,
      { wrapper },
    );

    expect(screen.getByRole("button", { name: /^Files/ })).toBeDisabled();
    expect(screen.getByLabelText("Runtime")).toBeDisabled();
    expect(screen.getByLabelText("Runs on")).toBeDisabled();
  });
});
