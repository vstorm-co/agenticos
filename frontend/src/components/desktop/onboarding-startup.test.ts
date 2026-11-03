import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const { resume, refresh } = vi.hoisted(() => ({
  resume: vi.fn(async () => {}),
  refresh: vi.fn(async () => {}),
}));
vi.mock("../../../../desktop/ui/local-computer.js", () => ({
  localComputerStep: () => Object.assign(refresh, { resume }),
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

async function start(deployment: "local" | "server", notice: string | null) {
  const invoke = vi.fn(async (command: string) => {
    if (command === "onboarding_state") return { deployment, server_url: "https://example.com/" };
    if (command === "startup_notice") return notice;
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
