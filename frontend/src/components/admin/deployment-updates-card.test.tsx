import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DeploymentUpdatesCard } from "./deployment-updates-card";

const mocks = vi.hoisted(() => ({
  mutate: vi.fn(),
  status: {
    data: {
      configured: true,
      reachable: true,
      pipeline_url: null as string | null,
      operation: null as {
        id: string;
        version: string;
        phase: string;
        scheduled_for?: number;
        reason?: string;
        backup_id?: string;
      } | null,
    },
    isError: false,
    refetch: vi.fn(),
  },
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/hooks/use-deployment-updates", () => ({
  useDeploymentUpdates: () => ({
    status: mocks.status,
    action: { mutate: mocks.mutate, isPending: false, isError: false },
  }),
}));
vi.mock("@/hooks/use-release-update", () => ({
  useReleaseUpdate: () => ({
    data: {
      latest: {
        version: "1.99.0",
        url: "https://github.com/vstorm-co/agenticos/releases/tag/v1.99.0",
      },
    },
    refetch: vi.fn(),
  }),
}));
beforeEach(() => {
  mocks.mutate.mockReset();
  mocks.status.data.configured = true;
  mocks.status.data.reachable = true;
  mocks.status.data.operation = null;
  mocks.status.data.pipeline_url = null;
});
it("prepares the advertised release but never applies it automatically", () => {
  render(<DeploymentUpdatesCard />);
  fireEvent.click(screen.getByRole("button", { name: "prepare" }));
  expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({
    kind: "prepare",
    payload: { version: "1.99.0" },
  });
  expect(screen.getByRole("link", { name: "changelog" })).toHaveAttribute(
    "href",
    expect.stringContaining("v1.99.0"),
  );
});
it("requires confirmation before applying a ready operation", () => {
  mocks.status.data.operation = { id: "a".repeat(32), version: "1.99.0", phase: "ready" };
  render(<DeploymentUpdatesCard />);
  fireEvent.click(screen.getByRole("button", { name: "updateNow" }));
  expect(mocks.mutate).not.toHaveBeenCalled();
  const buttons = screen.getAllByRole("button", { name: "updateNow" });
  fireEvent.click(buttons[buttons.length - 1]!);
  expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({
    kind: "apply",
    payload: { id: "a".repeat(32), scheduled_for: null },
  });
});
it("only permits a future schedule and can cancel a scheduled operation", () => {
  mocks.status.data.operation = { id: "b".repeat(32), version: "1.99.0", phase: "ready" };
  const view = render(<DeploymentUpdatesCard />);
  expect(screen.getByRole("button", { name: "schedule" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("scheduleTime"), {
    target: { value: "2020-01-01T12:00" },
  });
  expect(screen.getByRole("button", { name: "schedule" })).toBeDisabled();
  mocks.status.data.operation.phase = "scheduled";
  view.rerender(<DeploymentUpdatesCard />);
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  expect(mocks.mutate).toHaveBeenCalledWith({ kind: "cancel", payload: { id: "b".repeat(32) } });
});
it("shows setup when disconnected and exposes the configured pipeline alternative", () => {
  mocks.status.data.configured = false;
  mocks.status.data.reachable = false;
  mocks.status.data.pipeline_url = "https://github.com/company/platform/actions";
  render(<DeploymentUpdatesCard />);
  expect(screen.getByText("setupTitle")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "prepare" })).toBeDisabled();
  expect(screen.getByRole("link", { name: "pipeline" })).toHaveAttribute(
    "href",
    mocks.status.data.pipeline_url,
  );
});
it("keeps migration failure and recovery instructions visible", () => {
  mocks.status.data.operation = {
    id: "c".repeat(32),
    version: "1.99.0",
    phase: "failed",
    reason: "health_failed",
    backup_id: "c".repeat(32) + "/final",
  };
  render(<DeploymentUpdatesCard />);
  expect(screen.getByRole("alert")).toHaveTextContent("failure");
  expect(screen.getByText("recovery")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "updateNow" })).not.toBeInTheDocument();
});
