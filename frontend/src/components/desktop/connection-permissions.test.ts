import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { permissionStep } from "../../../../desktop/ui/permissions.js";

const denied = { supported: true, screen_capture: false, accessibility: false };
const invoke = vi.fn<(command: string, args?: Record<string, string>) => Promise<unknown>>();
const unsupported = vi.fn();

function step() {
  const root = document.querySelector<HTMLElement>('[data-screen="permissions"]');
  if (!root) throw new Error("Connection wizard permission step is missing");
  root.hidden = false;
  return { root, refresh: permissionStep(root, invoke, unsupported) };
}

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = readFileSync(
    resolve(process.cwd(), "../desktop/ui/index.html"),
    "utf8",
  );
  invoke.mockResolvedValue(denied);
});

describe("permissions in the connection wizard", () => {
  it("checks without requesting access and lets the person continue with neither permission", async () => {
    const { refresh } = step();
    await refresh();
    expect(invoke).toHaveBeenCalledExactlyOnceWith("onboarding_permissions");
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
    expect(screen.getAllByText("Not enabled")).toHaveLength(2);
  });

  it.each(["screen_capture", "accessibility"])(
    "requests only %s after its own button is clicked",
    async (permission) => {
      const { root, refresh } = step();
      await refresh();
      invoke.mockResolvedValueOnce({ ...denied, [permission]: true });
      const button = root.querySelector<HTMLButtonElement>(
        `[data-permission="${permission}"] button`,
      );
      if (!button) throw new Error("Permission button is missing");
      fireEvent.click(button);
      await waitFor(() => expect(button).toHaveTextContent("Allowed"));
      expect(button).toBeDisabled();
      expect(invoke).toHaveBeenLastCalledWith("request_onboarding_permission", { permission });
    },
  );

  it("updates after returning from System Settings and does not prompt again", async () => {
    const { refresh } = step();
    await refresh();
    invoke.mockResolvedValueOnce({ ...denied, screen_capture: true });
    await refresh();
    expect(screen.getByRole("button", { name: "Allowed" })).toBeDisabled();
    expect(invoke.mock.calls.every(([command]) => command === "onboarding_permissions")).toBe(true);
  });

  it("skips OS-specific requests on other platforms", async () => {
    invoke.mockResolvedValueOnce({ ...denied, supported: false });
    await step().refresh();
    expect(unsupported).toHaveBeenCalledOnce();
  });

  it.each([null, {}, { supported: "yes" }])(
    "reports an unreadable status without blocking continuation",
    async (status) => {
      invoke.mockResolvedValueOnce(status);
      await step().refresh();
      expect(screen.getByRole("alert")).toHaveTextContent("could not read");
      expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
    },
  );

  it("reports a failed request and lets the person try again", async () => {
    const { root } = step();
    invoke.mockRejectedValueOnce(new Error("System Settings could not open"));
    const button = root.querySelector<HTMLButtonElement>("[data-permission] button");
    if (!button) throw new Error("Permission button is missing");
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeEnabled());
    expect(screen.getByRole("alert")).toHaveTextContent("could not open");
  });
});
