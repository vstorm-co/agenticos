import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { WorkspaceReadNotice } from "./workspace-read-notice";
const permissions = vi.hoisted(() => ({ canManage: false }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => permissions.canManage }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
beforeEach(() => {
  permissions.canManage = false;
  vi.clearAllMocks();
});
it("keeps transport details out of the first reading and can retry in place", async () => {
  const retry = vi.fn().mockResolvedValue(undefined);
  render(
    <WorkspaceReadNotice
      detail="DNS lookup failed for private service"
      failed
      cloud
      onRetry={retry}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Could not load these files");
  expect(screen.getByText("DNS lookup failed for private service")).not.toBeVisible();
  await userEvent.click(screen.getByText("Technical details"));
  expect(screen.getByText("DNS lookup failed for private service")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(retry).toHaveBeenCalledOnce());
  expect(screen.queryByRole("link")).toBeNull();
});
it("keeps a configuration notice neutral and links administrators to actual sandbox settings", () => {
  permissions.canManage = true;
  const view = render(
    <WorkspaceReadNotice detail="No workspace root" failed={false} cloud onRetry={vi.fn()} />,
  );
  expect(screen.getByRole("status")).toHaveTextContent("Files are not available right now");
  expect(screen.getByRole("link", { name: "Sandbox connections" })).toHaveAttribute(
    "href",
    "/sandboxes",
  );
  view.rerender(
    <WorkspaceReadNotice detail="Local read refused" failed cloud={false} onRetry={vi.fn()} />,
  );
  expect(screen.queryByRole("link")).toBeNull();
});
it("retains the notice and reports a retry that itself fails", async () => {
  render(
    <WorkspaceReadNotice
      detail="Original cause"
      failed
      cloud
      onRetry={vi.fn().mockRejectedValue(new Error("Connection is still unavailable"))}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Connection is still unavailable"));
  expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  expect(screen.getByRole("alert")).toBeVisible();
});
