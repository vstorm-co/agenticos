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
  await screen.findByText("Docker is ready to open");
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
  expect(screen.getByLabelText("Instance name")).toHaveValue("Interrupted");
  fireEvent.click(screen.getByRole("button", { name: "New instance" }));
  expect(root.querySelector('[name="instance-id"]')).toHaveValue("");
  expect(screen.getByLabelText("Instance name")).toHaveValue("");
});
it("downloads Docker only after the explicit download action", async () => {
  invoke.mockResolvedValueOnce("no_docker");
  const { refresh } = mount();
  await refresh();
  expect(invoke.mock.calls.some(([name]) => name === "download_docker")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Download Docker Desktop" }));
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("download_docker"));
  expect(screen.getByRole("status")).toHaveTextContent("Finish installing Docker Desktop");
});
