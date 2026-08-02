import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { WorkspaceSection } from "./workspace-section";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

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
      backend: { type: "string", enum: ["state", "docker", "daytona"], default: "state" },
    },
  },
  contracts: [],
  requires_secret: null,
};

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

describe("WorkspaceSection", () => {
  it("renders nothing when the deployment did not register the capability", () => {
    // An empty section reads as something that failed to load.
    const { container } = render(
      <WorkspaceSection
        definition={undefined}
        binding={undefined}
        onToggle={vi.fn()}
        onChange={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("starts on None, and choosing a backend switches the capability on", async () => {
    const onToggle = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={undefined}
        onToggle={onToggle}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /^None/ })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(screen.getByRole("button", { name: /^Files/ }));

    expect(onToggle).toHaveBeenCalledWith("sandbox");
  });

  it("choosing None switches it back off", async () => {
    const onToggle = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state" })}
        onToggle={onToggle}
        onChange={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /^None/ }));

    expect(onToggle).toHaveBeenCalledWith("sandbox");
  });

  it("warns that a shared workspace is shared, because a schema cannot", async () => {
    // The one setting here that lets one person read another's files. It ships
    // without a permission of its own, so the consequence is made visible.
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state", session_scope: "agent" })}
        onToggle={vi.fn()}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText(/visible to the rest of the organization/i)).toBeVisible();
  });

  it("says nothing alarming about a workspace nobody else can read", () => {
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state", session_scope: "conversation" })}
        onToggle={vi.fn()}
        onChange={vi.fn()}
      />,
    );

    expect(screen.queryByText(/visible to the rest of the organization/i)).toBeNull();
  });

  it("offers a runtime only where there is a container to run it in", () => {
    const { rerender } = render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state" })}
        onToggle={vi.fn()}
        onChange={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText("Runtime")).toBeNull();

    rerender(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "docker" })}
        onToggle={vi.fn()}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Runtime")).toBeVisible();
  });

  it("clears a runtime when moving to a backend that runs no container", async () => {
    // Publish refuses the combination, so leaving it behind would fail in a
    // form somebody has already left.
    const onChange = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "docker", runtime: "python" })}
        onToggle={vi.fn()}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /^Files/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ backend: "state", runtime: null }),
      }),
    );
  });

  it("cannot offer a shell on the backend that has none", () => {
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state" })}
        onToggle={vi.fn()}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Allow shell commands")).toBeDisabled();
    expect(screen.getByText(/pair it with Run Python/i)).toBeVisible();
  });

  it("does not render the generated form as well as the choice", () => {
    // The schema would draw the same fields a second time.
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "docker" })}
        onToggle={vi.fn()}
        onChange={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText("backend")).toBeNull();
  });

  it("changing who shares it is written to the binding", async () => {
    const onChange = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "state", session_scope: "conversation" })}
        onToggle={vi.fn()}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Who shares it" }));
    await userEvent.click(screen.getByRole("option", { name: "Everyone using this agent" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ session_scope: "agent" }) }),
    );
  });

  it("a runtime reaches the binding as it is typed", async () => {
    const onChange = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "docker" })}
        onToggle={vi.fn()}
        onChange={onChange}
      />,
    );

    await userEvent.type(screen.getByLabelText("Runtime"), "p");

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ runtime: "p" }) }),
    );
  });

  it("clearing the runtime means the deployment's default, not an empty alias", async () => {
    // An empty string would be sent as a runtime the service has never heard of.
    const onChange = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "docker", runtime: "python" })}
        onToggle={vi.fn()}
        onChange={onChange}
      />,
    );

    await userEvent.clear(screen.getByLabelText("Runtime"));

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ runtime: null }) }),
    );
  });

  it("the shell can be removed from a backend that has one", async () => {
    const onChange = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "docker" })}
        onToggle={vi.fn()}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByLabelText("Allow shell commands"));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ include_execute: false }) }),
    );
  });

  it("a choice made before the binding exists cannot write to nothing", async () => {
    // `onToggle` creates the binding; the config patch lands on the next render
    // with the binding the parent then supplies.
    const onChange = vi.fn();
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={undefined}
        onToggle={vi.fn()}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /^Container/ }));

    expect(onChange).not.toHaveBeenCalled();
  });

  it("is inert for somebody who may not edit the agent", () => {
    render(
      <WorkspaceSection
        definition={SANDBOX}
        binding={binding({ backend: "docker" })}
        onToggle={vi.fn()}
        onChange={vi.fn()}
        disabled
      />,
    );

    expect(screen.getByRole("button", { name: /^None/ })).toBeDisabled();
    expect(screen.getByLabelText("Runtime")).toBeDisabled();
  });
});
