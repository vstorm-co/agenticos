import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConnectionsTable } from "./connections-table";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";

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

function mount(rows: SandboxConnectionRecord[]) {
  const handlers = { onEdit: vi.fn(), onInspect: vi.fn(), onDelete: vi.fn() };
  render(<ConnectionsTable connections={rows} {...handlers} />);
  return handlers;
}

describe("ConnectionsTable", () => {
  it("says which host an agent gets when it names none", () => {
    // The only question this table exists to answer at a glance.
    mount([connection(), connection({ id: "c-2", name: "Big box", is_default: false })]);

    expect(screen.getByText("Default")).toBeVisible();
  });

  it("marks a connection that was switched off", () => {
    // It resolves for nothing, and a row that looked normal would leave an
    // operator hunting the wrong cause.
    mount([connection({ is_active: false })]);

    expect(screen.getByText("Off")).toBeVisible();
  });

  it("says a credential is missing rather than leaving the cell blank", () => {
    // It resolves and then refuses every session, inside somebody's
    // conversation rather than here.
    mount([connection({ secret_id: null })]);

    expect(screen.getByText("Missing")).toBeVisible();
  });

  it("never prints the credential itself, only that there is one", () => {
    mount([connection()]);

    expect(screen.getByText("In the vault")).toBeVisible();
    expect(screen.queryByText("s-1")).toBeNull();
  });

  it("names Daytona's address as theirs rather than showing an empty one", () => {
    // A blank cell reads as a misconfiguration rather than as the answer.
    mount([connection({ kind: "daytona", base_url: null })]);

    expect(screen.getByText("Daytona cloud")).toBeVisible();
    expect(screen.getByText("their API")).toBeVisible();
  });

  it("shows a container connection with no address as unset", () => {
    mount([connection({ base_url: null })]);

    expect(screen.getByText("—")).toBeVisible();
  });

  it("says the service decides the runtime when the connection does not", () => {
    mount([connection({ default_runtime: null })]);

    expect(screen.getByText("the service's own")).toBeVisible();
  });

  it("offers the policy only where there is a service to ask", () => {
    // Daytona publishes none: what it allows is an account setting on their side.
    mount([connection(), connection({ id: "c-2", name: "Daytona", kind: "daytona" })]);

    expect(screen.getAllByRole("button", { name: /What .* allows/ })).toHaveLength(1);
  });

  it("sorts by name when its header is pressed, since the caller holds every row", async () => {
    mount([
      connection({ id: "c-1", name: "Local Docker" }),
      connection({ id: "c-2", name: "Big box", is_default: false }),
    ]);

    await userEvent.click(screen.getByRole("button", { name: "Name" }));
    await userEvent.click(screen.getByRole("button", { name: "Name" }));

    const names = Array.from(
      screen.getAllByRole("rowgroup")[1]!.querySelectorAll("tr > td:first-child"),
      (cell) => cell.textContent,
    );
    expect(names).toEqual(["Big box", expect.stringContaining("Local Docker")]);
  });

  it("hands each action the row it was pressed on", async () => {
    const handlers = mount([connection()]);

    await userEvent.click(screen.getByRole("button", { name: "What Local Docker allows" }));
    await userEvent.click(screen.getByRole("button", { name: "Edit Local Docker" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete Local Docker" }));

    expect(handlers.onInspect).toHaveBeenCalledWith(expect.objectContaining({ id: "c-1" }));
    expect(handlers.onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: "c-1" }));
    expect(handlers.onDelete).toHaveBeenCalledWith(expect.objectContaining({ id: "c-1" }));
  });
});
