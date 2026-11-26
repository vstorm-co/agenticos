import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProjectFilter } from "./project-filter";
import type { Project } from "@/types/projects";
const state = vi.hoisted(() => ({ can: true, project: null as { name: string } | null }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => state.can }) }));
vi.mock("@/hooks/use-projects", () => ({ useProject: () => ({ project: state.project }) }));
vi.mock("./project-picker-dialog", () => ({
  ProjectPickerDialog: ({
    open,
    onPick,
    onOpenChange,
    includeReadOnly,
  }: {
    open: boolean;
    onPick: (project: Project | null) => void;
    onOpenChange: (open: boolean) => void;
    includeReadOnly: boolean;
  }) =>
    open ? (
      <div>
        <span>{String(includeReadOnly)}</span>
        <button
          onClick={() => {
            onPick({ id: "p" } as Project);
            onOpenChange(false);
          }}
        >
          Pick
        </button>
        <button onClick={() => onPick(null)}>All</button>
      </div>
    ) : null,
}));
beforeEach(() => {
  state.can = true;
  state.project = null;
});
it("is hidden without project-list permission", () => {
  state.can = false;
  const { container } = render(<ProjectFilter value={null} onChange={vi.fn()} />);
  expect(container).toBeEmptyDOMElement();
});
it("offers read-only projects and keeps the selected id in caller state", async () => {
  const change = vi.fn();
  render(<ProjectFilter value={null} onChange={change} />);
  await userEvent.click(screen.getByRole("button", { name: "Projects" }));
  expect(screen.getByText("true")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "All" }));
  expect(change).toHaveBeenCalledWith(null);
  await userEvent.click(screen.getByRole("button", { name: "Pick" }));
  expect(change).toHaveBeenLastCalledWith("p");
});
it("shows the project name when available and lets the member clear the filter", async () => {
  const change = vi.fn();
  const { rerender } = render(<ProjectFilter value="p" onChange={change} />);
  expect(screen.getByRole("button", { name: "Projects" })).toBeVisible();
  state.project = { name: "Launch" };
  rerender(<ProjectFilter value="p" onChange={change} />);
  expect(screen.getByRole("button", { name: "Launch" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(change).toHaveBeenCalledWith(null);
});
