import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EditorLoading, FileEditorLoading } from "./editor-loading";

const permissions = vi.hoisted(() => ({ runs: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => permissions.runs }),
}));

describe("editor loading slots", () => {
  for (const kind of ["skill", "context"] as const) {
    for (const canEdit of [true, false]) {
      it(`preserves ${kind} ${canEdit ? "editor" : "reader"} chrome without exposing fake controls`, () => {
        permissions.runs = true;
        const { container } = render(<EditorLoading kind={kind} canEdit={canEdit} />);
        expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
        expect(screen.queryByRole("button")).toBeNull();
        expect(container.querySelector("[inert]")).not.toBeNull();
        expect(screen.getByText(canEdit ? "Cancel" : "Close")).toBeInTheDocument();
        expect(screen.queryByText("Save")).toBe(canEdit ? screen.getByText("Save") : null);
        expect(screen.queryByText("Improve with the assistant") !== null).toBe(
          kind === "context" && canEdit,
        );
      });
    }
  }
  it("omits shared file write slots on a fork", () => {
    const { container } = render(<EditorLoading kind="skill" files={false} />);
    expect(container.querySelector(".grid-cols-3")).toBeNull();
    expect(screen.getByText("Save")).toBeInTheDocument();
  });
  it("does not promise improvement actions without run access", () => {
    permissions.runs = false;
    render(<EditorLoading kind="context" />);
    expect(screen.queryByText("Improve with the assistant")).toBeNull();
    expect(screen.getByText("Save")).toBeInTheDocument();
  });
  it("reserves the full-view footer action in the catalog editor", () => {
    render(<EditorLoading kind="skill" fullView />);
    expect(screen.getByText("Open full view")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open full view" })).toBeNull();
  });
  it("keeps a named pane's toolbar and content placeholders together", () => {
    const { container } = render(<FileEditorLoading />);
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector(".border-b")).not.toBeNull();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(3);
  });
});
