import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { startLanguage } from "../../../../desktop/ui/language.js";
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
  document.documentElement.lang = "en";
  localStorage.clear();
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
  expect(document.querySelector("[data-local-message]")).toHaveTextContent("Server unavailable");
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
  expect(document.querySelector("[data-local-message]")).toHaveTextContent(
    "Installation cancelled",
  );
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
  expect(document.querySelector("[data-local-message]")).toHaveTextContent(
    "Runtime could not start",
  );
  expect(screen.getByRole("button", { name: "New instance" })).toBeEnabled();
});

it("keeps an explicit continuation for platforms using an external installer", async () => {
  invoke.mockImplementation(async (command) => (command === "local_instances" ? [] : "no_docker"));
  const { refresh } = mount();
  await refresh();
  fireEvent.click(screen.getByRole("button", { name: "Set up this computer" }));
  await waitFor(() =>
    expect(document.querySelector("[data-local-message]")).toHaveTextContent(
      "Complete the runtime installation",
    ),
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

const outdated = {
  id: "work",
  name: "Work",
  url: "http://localhost:3001/",
  installed: true,
  running: true,
  version: "1.80.0",
  target_version: "1.82.2",
  can_update: true,
};

it("shows workspace and target versions and updates only the chosen managed instance", async () => {
  let finish: ((value: unknown) => void) | undefined;
  invoke.mockImplementation(async (command) => {
    if (command === "local_instances") return [outdated];
    if (command === "update_local")
      return new Promise((resolve) => {
        finish = resolve;
      });
    return "running";
  });
  const { root, refresh } = mount();
  await refresh();
  expect(screen.getByText("Update target").parentElement).toHaveTextContent(
    "Workspace 1.80.0 · Update target 1.82.2",
  );
  const update = screen.getByRole("button", { name: "Update local workspace" });
  fireEvent.click(update);
  fireEvent.click(update);
  expect(invoke.mock.calls.filter(([name]) => name === "update_local")).toEqual([
    ["update_local", { instanceId: "work" }],
  ]);
  expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
  expect(root.querySelector("[data-local-update-progress]")).toBeVisible();
  refresh.progress({ step: "backup" });
  expect(screen.getByText("Backing up the database, files and keys…")).toBeVisible();
  refresh.progress({ step: "restart" });
  expect(screen.getByText("Restarting the workspace and checking health…")).toBeVisible();
  finish?.(true);
  await screen.findByText("Workspace updated. Connect to continue.");
  expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled();
});

it.each([false, "failure"])(
  "restores update controls after cancellation or failure: %s",
  async (result) => {
    invoke.mockImplementation(async (command) => {
      if (command === "local_instances") return [outdated];
      if (command === "update_local") {
        if (result === "failure") throw new Error("Backup failed. Free disk space and retry.");
        return result;
      }
      return "running";
    });
    const { refresh } = mount();
    await refresh();
    fireEvent.click(screen.getByRole("button", { name: "Update local workspace" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Update local workspace" })).toBeEnabled(),
    );
    if (result === "failure")
      expect(screen.getByRole("alert")).toHaveTextContent("Free disk space and retry");
    else expect(screen.getByText("Workspace update cancelled.")).toBeVisible();
  },
);

it("offers no update on an unfinished or newer workspace", async () => {
  invoke.mockImplementation(async (command) =>
    command === "local_instances"
      ? [
          { ...outdated, version: "1.99.0", can_update: false },
          { ...outdated, id: "partial", installed: false },
        ]
      : "running",
  );
  const { refresh } = mount();
  await refresh();
  expect(screen.queryByRole("button", { name: "Update local workspace" })).toBeNull();
});

it("permits reapplying the current release to recover an interrupted update", async () => {
  invoke.mockImplementation(async (command) =>
    command === "local_instances"
      ? [{ ...outdated, version: outdated.target_version }]
      : command === "update_local"
        ? false
        : "running",
  );
  const { refresh } = mount();
  await refresh();
  fireEvent.click(screen.getByRole("button", { name: "Reapply workspace update" }));
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("update_local", { instanceId: "work" }));
});

it("keeps healthy instances available when another workspace version cannot be read", async () => {
  invoke.mockImplementation(async (command) =>
    command === "local_instances"
      ? [
          {
            ...outdated,
            id: "damaged",
            name: "Damaged",
            version: null,
            version_error: "The version file cannot be read",
            can_update: false,
          },
          outdated,
        ]
      : "running",
  );
  const { refresh } = mount();
  await refresh();
  expect(screen.getByText("Damaged")).toBeVisible();
  expect(screen.getByText("The version file cannot be read")).toBeVisible();
  expect(screen.getAllByRole("button", { name: "Connect" })).toHaveLength(2);
  expect(screen.getAllByRole("button", { name: "Update local workspace" })).toHaveLength(1);
});

it("translates update labels on language changes without translating instance names or versions", async () => {
  invoke.mockImplementation(async (command) =>
    command === "local_instances" ? [{ ...outdated, name: "Workspace" }] : "running",
  );
  localStorage.setItem("agenticos:start-language", "en");
  await startLanguage(invoke);
  const { refresh } = mount();
  await refresh();
  const language = document.querySelector<HTMLSelectElement>("#language");
  if (!language) throw new Error("Language control is missing");
  fireEvent.change(language, { target: { value: "pl" } });
  await screen.findByRole("button", { name: "Zaktualizuj lokalny workspace" });
  expect(screen.getByText("Wersja docelowa").parentElement).toHaveTextContent("1.80.0");
  expect(document.querySelector(".instance-row strong")).toHaveTextContent("Workspace");
  fireEvent.change(language, { target: { value: "en" } });
  await screen.findByRole("button", { name: "Update local workspace" });
  expect(screen.getByText("Update target").parentElement).toHaveTextContent("1.82.2");
});
