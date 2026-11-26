import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ProjectRows } from "./project-rows";

let canUse = true;
let moving = false;
vi.mock("next/navigation", () => ({ usePathname: () => "/chat" }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock("@/hooks/use-projects", () => ({
  useProjects: () => ({
    projects: [
      {
        id: "sales",
        name: "Sales",
        can_use: canUse,
        workspace_move: moving ? { status: "running" } : null,
      },
    ],
  }),
}));
beforeEach(() => {
  canUse = true;
  moving = false;
});
it("starts a project chat directly from the general sidebar and closes mobile navigation", () => {
  const navigate = vi.fn();
  render(<ProjectRows collapsed={false} onNavigate={navigate} />);
  const link = screen.getByRole("link", { name: "New chat in Sales" });
  expect(link).toHaveAttribute("href", "/chat?project=sales");
  fireEvent.click(link);
  expect(navigate).toHaveBeenCalledOnce();
});
it("keeps project navigation but hides chat creation from readers", () => {
  canUse = false;
  render(<ProjectRows collapsed={false} />);
  expect(screen.getByRole("link", { name: "Sales" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "New chat in Sales" })).not.toBeInTheDocument();
});
it("does not offer chat creation while a project workspace is moving or on the collapsed rail", () => {
  moving = true;
  const view = render(<ProjectRows collapsed={false} />);
  expect(screen.queryByRole("link", { name: "New chat in Sales" })).not.toBeInTheDocument();
  moving = false;
  view.rerender(<ProjectRows collapsed />);
  expect(screen.queryByRole("link", { name: "New chat in Sales" })).not.toBeInTheDocument();
});
