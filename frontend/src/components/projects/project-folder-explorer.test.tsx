import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { ProjectFolderExplorer } from "./project-folder-explorer";

const local = vi.hoisted(() => ({ read: vi.fn(), refresh: vi.fn() }));
vi.mock("@/hooks/use-desktop", () => ({ useLocalWorkspace: local.read }));
vi.mock("@/components/sandboxes/workspace-explorer", () => ({
  FileExplorer: ({
    source,
    error,
    toolbar,
    onRemove,
  }: {
    source: { kind: string; root: string };
    error: string | null;
    toolbar: ReactNode;
    onRemove?: unknown;
  }) => (
    <div>
      <p>
        {source.kind}:{source.root}
      </p>
      {error && <p role="alert">{error}</p>}
      {toolbar}
      {Boolean(onRemove) && <button>Remove</button>}
    </div>
  ),
}));
beforeEach(() => {
  local.refresh.mockReset();
  local.read.mockReturnValue({ workspace: null, error: null, refresh: local.refresh });
});
it("uses the approved native root without offering shared upload or deletion", async () => {
  render(<ProjectFolderExplorer root="/approved/launch" />);
  expect(local.read).toHaveBeenCalledWith("/approved/launch", "/approved/launch");
  expect(screen.getByText("local:/approved/launch")).toBeVisible();
  expect(screen.queryByRole("button", { name: /upload|remove/i })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Refresh files" }));
  expect(local.refresh).toHaveBeenCalledOnce();
});
it("keeps native refusal visible rather than opening shared server files", () => {
  local.read.mockReturnValue({
    workspace: null,
    error: "Folder access revoked",
    refresh: local.refresh,
  });
  render(<ProjectFolderExplorer root="/revoked" />);
  expect(screen.getByRole("alert")).toHaveTextContent("Folder access revoked");
  expect(screen.getByText("local:/revoked")).toBeVisible();
});
