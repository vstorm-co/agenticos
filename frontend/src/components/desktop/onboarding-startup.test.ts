import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const { resume, refresh, prepare } = vi.hoisted(() => ({
  resume: vi.fn(async () => {}),
  prepare: vi.fn(async () => {}),
  refresh: vi.fn(async () => {}),
}));
vi.mock("../../../../desktop/ui/local-computer.js", () => ({
  localComputerStep: () => Object.assign(refresh, { resume, prepare }),
}));
vi.mock("../../../../desktop/ui/permissions.js", () => ({
  permissionStep: () => vi.fn(async () => {}),
}));

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  document.body.innerHTML = readFileSync(
    resolve(process.cwd(), "../desktop/ui/index.html"),
    "utf8",
  );
});

async function start(deployment: "local" | "server", notice: string | null, pending = false) {
  const invoke = vi.fn(async (command: string) => {
    if (command === "onboarding_state")
      return { deployment, server_url: "https://example.com/", local_setup_pending: pending };
    if (command === "startup_notice") return notice;
    if (command === "set_onboarding_language") return undefined;
    throw new Error(`Unexpected startup command: ${command}`);
  });
  Object.defineProperty(window, "__TAURI__", {
    configurable: true,
    value: { core: { invoke }, event: { listen: vi.fn(async () => {}) } },
  });
  await import("../../../../desktop/ui/onboarding.js");
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("startup_notice"));
}

it("automatically resumes a saved local connection that stopped answering", async () => {
  await start("local", "Workspace stopped");
  await waitFor(() => expect(resume).toHaveBeenCalledOnce());
  expect(document.querySelector('[data-screen="local"]')).not.toHaveAttribute("hidden");
});

it("shows the connection error for an external server without starting a local engine", async () => {
  await start("server", "Server unavailable");
  await waitFor(() =>
    expect(document.querySelector("#server-form .error")).toHaveTextContent("Server unavailable"),
  );
  expect(resume).not.toHaveBeenCalled();
});

it("does not restart a workspace when the startup probe succeeded", async () => {
  await start("local", null);
  await waitFor(() =>
    expect(document.querySelector('[data-screen="where"]')).not.toHaveAttribute("hidden"),
  );
  expect(resume).not.toHaveBeenCalled();
});

it("continues an explicitly started runtime installation after a restart", async () => {
  await start("local", null, true);
  await waitFor(() => expect(prepare).toHaveBeenCalledOnce());
  expect(resume).not.toHaveBeenCalled();
});

it("retries a failed setup using the instance identity reported by native progress", async () => {
  const callbacks = new Map<
    string,
    (event: { payload: { step: string; instance_id: string } }) => void
  >();
  const invoke = vi.fn(async (command: string) => {
    if (command === "onboarding_state") return { deployment: "local", server_url: null };
    if (command === "startup_notice") return null;
    if (command === "set_up_local") {
      callbacks.get("local:progress")?.({
        payload: { step: "download", instance_id: "saved-instance" },
      });
      throw new Error("Connection interrupted");
    }
    return undefined;
  });
  Object.defineProperty(window, "__TAURI__", {
    configurable: true,
    value: {
      core: { invoke },
      event: {
        listen: vi.fn(
          async (
            name: string,
            callback: (event: { payload: { step: string; instance_id: string } }) => void,
          ) => {
            callbacks.set(name, callback);
          },
        ),
      },
    },
  });
  await import("../../../../desktop/ui/onboarding.js");
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("startup_notice"));
  const form = document.querySelector<HTMLFormElement>("#local-form");
  if (!form) throw new Error("Local setup form is missing");
  for (const [name, value] of Object.entries({
    "instance-name": "Work",
    organization: "Example",
    email: "test@example.com",
    password: "test-password",
  })) {
    const field = form.querySelector<HTMLInputElement>(`[name="${name}"]`);
    if (!field) throw new Error("Setup field is missing");
    field.value = value;
  }
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await waitFor(() =>
    expect(document.querySelector("[data-retry-setup]")).not.toHaveAttribute("hidden"),
  );
  await waitFor(() =>
    expect(document.querySelector("[data-progress-actions]")).not.toHaveAttribute("hidden"),
  );
  document.querySelector<HTMLButtonElement>("[data-retry-setup]")?.click();
  await waitFor(() =>
    expect(invoke.mock.calls.filter(([command]) => command === "set_up_local")).toHaveLength(2),
  );
  expect(invoke).toHaveBeenLastCalledWith("set_up_local", {
    owner: expect.objectContaining({ instance_id: "saved-instance" }),
  });
});
