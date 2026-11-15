import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { localComputerStep } from "../../../../desktop/ui/local-computer.js";

const invoke = vi.fn<(command: string, args?: Record<string, string>) => Promise<unknown>>();
function mount() {
  const root = document.querySelector<HTMLElement>('[data-screen="local"]');
  if (!root) throw new Error("Local setup is missing");
  root.hidden = false;
  return { root, refresh: localComputerStep(root, invoke, vi.fn()) };
}
beforeEach(() => {
  vi.clearAllMocks();
  invoke.mockReset();
  invoke.mockImplementation(async (command) => (command === "local_instances" ? [] : "ready"));
  document.body.innerHTML = readFileSync(
    resolve(process.cwd(), "../desktop/ui/index.html"),
    "utf8",
  );
});
it("keeps a visible status card and Back action during the probe", async () => {
  let resolveStatus: ((value: unknown) => void) | undefined;
  invoke.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveStatus = resolve;
      }),
  );
  const { root, refresh } = mount();
  const pending = refresh();
  expect(root.querySelector("[data-local-instance]")).toHaveAttribute("aria-busy", "true");
  expect(screen.getByRole("button", { name: "Back" })).toBeEnabled();
  resolveStatus?.("running");
  await pending;
  expect(screen.getByText("Your local workspace is ready")).toBeVisible();
  expect(screen.getByRole("button", { name: "Connect and continue" })).toBeEnabled();
});
it("gives immediate connecting feedback, refuses duplicate clicks and permits retry after failure", async () => {
  invoke.mockResolvedValueOnce("running");
  const { refresh } = mount();
  await refresh();
  let rejectConnection: ((error: Error) => void) | undefined;
  invoke.mockImplementationOnce(
    () =>
      new Promise((_resolve, reject) => {
        rejectConnection = reject;
      }),
  );
  const button = screen.getByRole("button", { name: "Connect and continue" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(button).toBeDisabled();
  expect(button).toHaveTextContent("Connecting…");
  expect(invoke.mock.calls.filter(([command]) => command === "use_local")).toHaveLength(1);
  rejectConnection?.(new Error("Server unavailable"));
  await waitFor(() => expect(button).toBeEnabled());
  expect(screen.getByRole("status")).toHaveTextContent("Server unavailable");
});
it("reports a failed probe and exposes a working check-again action", async () => {
  invoke.mockRejectedValueOnce(new Error("Docker unavailable"));
  const { refresh } = mount();
  await refresh();
  invoke.mockResolvedValueOnce("docker_stopped");
  fireEvent.click(screen.getByRole("button", { name: "Check again" }));
  await screen.findByText("Start your local workspace");
});
it("ignores a stale probe result after a newer check", async () => {
  let resolveOld: ((value: unknown) => void) | undefined;
  invoke.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveOld = resolve;
      }),
  );
  const { refresh } = mount();
  const old = refresh();
  invoke.mockResolvedValueOnce("running");
  await refresh();
  resolveOld?.("no_docker");
  await old;
  expect(screen.getByText("Your local workspace is ready")).toBeVisible();
});

it("lists separate managed instances and connects using the selected identity", async () => {
  invoke.mockImplementation(async (command) =>
    command === "local_instances"
      ? [
          {
            id: "work",
            name: "Work",
            url: "http://localhost:3001/",
            running: true,
            installed: true,
          },
          {
            id: "test",
            name: "Testing",
            url: "http://localhost:3002/",
            running: false,
            installed: true,
          },
        ]
      : "running",
  );
  const { refresh } = mount();
  await refresh();
  await screen.findByText("Testing");
  fireEvent.click(screen.getByRole("button", { name: "Start and connect" }));
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("use_local", { instanceId: "test" }));
});
it("resumes a partial installation and offers a fresh instance beside an existing one", async () => {
  invoke.mockImplementation(async (command) =>
    command === "local_instances"
      ? [
          {
            id: "partial",
            name: "Interrupted",
            url: "http://localhost:3002/",
            installed: false,
            running: false,
          },
        ]
      : "running",
  );
  const { root, refresh } = mount();
  await refresh();
  fireEvent.click(await screen.findByRole("button", { name: "Finish setup" }));
  expect(root.querySelector('[name="instance-id"]')).toHaveValue("partial");
  expect(screen.getByLabelText("Workspace name")).toHaveValue("Interrupted");
  expect(screen.queryByRole("button", { name: "New instance" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "New instance" }));
  expect(root.querySelector('[name="instance-id"]')).toHaveValue("");
  expect(screen.getByLabelText("Workspace name")).toHaveValue("");
});
it("prepares the runtime only after setup, then opens the workspace form automatically", async () => {
  invoke.mockResolvedValueOnce("no_docker");
  const { refresh } = mount();
  await refresh();
  expect(invoke.mock.calls.some(([name]) => name === "download_docker")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Set up this computer" }));
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("download_docker"));
  await screen.findByRole("heading", { name: "Create a local instance" });
});

it("shows a separate, grouped creation step with one action bar and restores the overview on Cancel", async () => {
  invoke.mockResolvedValueOnce("running");
  const { root, refresh } = mount();
  await refresh();
  fireEvent.click(screen.getByRole("button", { name: "New instance" }));
  expect(screen.getByRole("heading", { name: "Create a local instance" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Connect and continue" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Workspace" })).toBeVisible();
  expect(screen.getByRole("group", { name: "Owner account" })).toBeVisible();
  expect(screen.getByRole("group", { name: "AI provider" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Create instance" })).toBeVisible();
  expect(root).toHaveAttribute("data-view", "create");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Connect and continue" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Create instance" })).not.toBeInTheDocument();
  expect(root).toHaveAttribute("data-view", "overview");
});

it("starts an installed runtime and continues without a manual status check", async () => {
  invoke.mockResolvedValueOnce("docker_stopped");
  const { refresh } = mount();
  await refresh();
  fireEvent.click(screen.getByRole("button", { name: "Start workspace" }));
  await screen.findByRole("heading", { name: "Create a local instance" });
  expect(invoke).toHaveBeenCalledWith("open_docker");
});

it("keeps saved instances visible after preparing the runtime", async () => {
  invoke.mockImplementation(async (command) => {
    if (command === "local_status") return "ready";
    if (command === "local_instances")
      return [
        {
          id: "work",
          name: "Work",
          url: "http://localhost:3001/",
          installed: true,
          running: false,
        },
      ];
    return undefined;
  });
  invoke.mockResolvedValueOnce("docker_stopped");
  const { refresh } = mount();
  await refresh();
  await refresh.prepare();
  expect(invoke).toHaveBeenCalledWith("download_docker");
  expect(screen.getByRole("heading", { name: "AgenticOS on this computer" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Start and connect" })).toBeVisible();
  expect(
    screen.queryByRole("heading", { name: "Create a local instance" }),
  ).not.toBeInTheDocument();
});

it("refuses duplicate preparation and restores a retry after cancellation", async () => {
  invoke.mockResolvedValueOnce("no_docker");
  const { refresh } = mount();
  await refresh();
  let rejectPreparation: ((error: Error) => void) | undefined;
  invoke.mockImplementationOnce(
    () =>
      new Promise((_resolve, reject) => {
        rejectPreparation = reject;
      }),
  );
  const button = screen.getByRole("button", { name: "Set up this computer" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(invoke.mock.calls.filter(([name]) => name === "download_docker")).toHaveLength(1);
  rejectPreparation?.(new Error("Installation cancelled"));
  await screen.findByText("Setup needs your attention");
  expect(screen.getByRole("button", { name: "Set up this computer" })).toBeEnabled();
  expect(screen.getByRole("status")).toHaveTextContent("Installation cancelled");
});

it("resumes the saved local workspace without sending owner secrets or creating an instance", async () => {
  invoke.mockResolvedValueOnce(true);
  const { root, refresh } = mount();
  await refresh.resume();
  expect(invoke).toHaveBeenCalledExactlyOnceWith("resume_local");
  expect(screen.getByText("Starting AgenticOS")).toBeVisible();
  expect(root.querySelector("[data-local-instance]")).toHaveAttribute("aria-busy", "false");
});

it("offers recovery when automatic startup fails", async () => {
  invoke.mockRejectedValueOnce(new Error("Runtime could not start"));
  const { refresh } = mount();
  await refresh.resume();
  expect(screen.getByText("Your workspace could not start")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("Runtime could not start");
  expect(screen.getByRole("button", { name: "New instance" })).toBeEnabled();
});

it("keeps an explicit continuation for platforms using an external installer", async () => {
  invoke.mockImplementation(async (command) => (command === "local_instances" ? [] : "no_docker"));
  const { refresh } = mount();
  await refresh();
  fireEvent.click(screen.getByRole("button", { name: "Set up this computer" }));
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("Complete the runtime installation"),
  );
  expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
});

it("offers installation if an installed CLI cannot start its runtime", async () => {
  invoke.mockResolvedValueOnce("docker_stopped");
  const { refresh } = mount();
  await refresh();
  invoke.mockRejectedValueOnce(new Error("The local runtime needs installation"));
  fireEvent.click(screen.getByRole("button", { name: "Start workspace" }));
  await screen.findByText("Setup needs your attention");
  expect(screen.getByRole("button", { name: "Set up this computer" })).toBeEnabled();
});

it("leaves unmanaged development stacks to the regular connection flow", async () => {
  invoke.mockResolvedValueOnce(false);
  const { refresh } = mount();
  await refresh.resume();
  expect(screen.getByText("Ready to create your workspace")).toBeVisible();
  expect(invoke).not.toHaveBeenCalledWith("set_up_local");
});
