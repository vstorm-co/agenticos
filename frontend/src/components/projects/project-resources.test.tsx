import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProjectResources } from "./project-resources";
import type { Project } from "@/types/projects";

const state = vi.hoisted(() => ({
  data: {
    items: [
      {
        kind: "workflow",
        resource_id: "w1",
        name: "Main flow",
        description: null,
        is_entrypoint: true,
      },
    ],
    total: 1,
  },
  isLoading: false,
  error: null as Error | null,
  add: { mutate: vi.fn(), error: null, isPending: false },
  remove: { mutate: vi.fn(), error: null, isPending: false },
  entrypoint: { mutate: vi.fn(), error: null, isPending: false },
}));
vi.mock("@/hooks/use-project-resources", () => ({
  useProjectResources: () => state,
  useProjectResourceCandidates: () => candidates,
}));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));
const candidates = vi.hoisted(() => ({
  data: [
    { id: "w1", name: "Main flow" },
    { id: "w2", name: "Another flow" },
  ],
  isLoading: false,
  error: null as Error | null,
}));
beforeEach(() => {
  vi.clearAllMocks();
  state.isLoading = false;
  state.error = null;
  candidates.error = null;
  candidates.isLoading = false;
  state.data = {
    items: [
      {
        kind: "workflow",
        resource_id: "w1",
        name: "Main flow",
        description: null,
        is_entrypoint: true,
      },
    ],
    total: 1,
  };
});
const project = { id: "p", can_edit: true } as Project;
it("uses the existing workflow route and lets editors remove only its link", async () => {
  render(<ProjectResources project={project} />);
  expect(screen.getByRole("link", { name: "Main flow" })).toHaveAttribute("href", "/workflows/w1");
  await userEvent.click(screen.getByRole("button", { name: "Clear main workflow" }));
  expect(state.entrypoint.mutate).toHaveBeenCalledWith(null);
  await userEvent.click(screen.getByRole("button", { name: "Remove Main flow from project" }));
  expect(state.remove.mutate).toHaveBeenCalledWith(state.data.items[0]);
});
it("does not offer writes to a read-only project viewer", () => {
  render(<ProjectResources project={{ ...project, can_edit: false }} />);
  expect(screen.queryByRole("button", { name: "Add existing resources" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Remove Main/ })).not.toBeInTheDocument();
});
it("submits selected existing resources as links without creating copies", async () => {
  render(<ProjectResources project={project} />);
  await userEvent.click(screen.getByRole("button", { name: "Add existing resources" }));
  const checkbox = screen.getByRole("checkbox", { name: "Another flow" });
  await userEvent.click(checkbox);
  await userEvent.click(screen.getByRole("button", { name: "Add selected (1)" }));
  expect(state.add.mutate).toHaveBeenCalledWith(
    [{ kind: "agent", resource_id: "w2" }],
    expect.objectContaining({ onSuccess: expect.any(Function) }),
  );
});

it("shows loading, empty results and explicit failures", () => {
  state.isLoading = true;
  const { rerender } = render(<ProjectResources project={project} />);
  state.isLoading = false;
  state.data = { items: [], total: 0 };
  rerender(<ProjectResources project={project} />);
  expect(screen.getByText("No linked resources")).toBeVisible();
  state.error = new Error("Unavailable");
  rerender(<ProjectResources project={project} />);
  expect(screen.getByRole("alert")).toBeVisible();
});
it("marks a workflow as main and searches the linked list", async () => {
  state.data.items.forEach((item) => {
    item.is_entrypoint = false;
  });
  render(<ProjectResources project={project} />);
  await userEvent.click(screen.getByRole("button", { name: "Set as main workflow" }));
  expect(state.entrypoint.mutate).toHaveBeenCalledWith("w1");
  await userEvent.type(screen.getByPlaceholderText("Search resources"), "research");
  expect(screen.getByPlaceholderText("Search resources")).toHaveValue("research");
});
it("switches resource type, preserves existing links and can cancel or dismiss", async () => {
  render(<ProjectResources project={project} />);
  await userEvent.click(screen.getByRole("button", { name: "Add existing resources" }));
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "Workflow" }));
  expect(screen.getByRole("checkbox", { name: "Main flow" })).toBeDisabled();
  const another = screen.getByRole("checkbox", { name: "Another flow" });
  await userEvent.click(another);
  await userEvent.click(another);
  expect(screen.getByRole("button", { name: "Add selected (0)" })).toBeDisabled();
  await userEvent.type(
    within(screen.getByRole("dialog")).getByPlaceholderText("Search resources"),
    "nothing",
  );
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Add existing resources" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("renders candidate loading and errors inside the dialog", async () => {
  candidates.isLoading = true;
  const { rerender } = render(<ProjectResources project={project} />);
  await userEvent.click(screen.getByRole("button", { name: "Add existing resources" }));
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  candidates.isLoading = false;
  candidates.error = new Error("Unavailable");
  rerender(<ProjectResources project={project} />);
  expect(screen.getByRole("alert")).toBeVisible();
});
