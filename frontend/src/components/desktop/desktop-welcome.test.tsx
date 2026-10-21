import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopWelcome } from "./desktop-welcome";
import { DESKTOP_STATE, MAC_MAIN } from "./fixtures";

const env = vi.hoisted(() => ({
  shell: null as unknown,
  auth: { isAuthenticated: true, isLoading: false },
  state: null as unknown,
  setBlobby: vi.fn(),
  setWindow: vi.fn(),
  replace: vi.fn(),
  finish: vi.fn(async () => {}),
  notify: vi.fn(async () => {}),
  report: vi.fn(),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => env.auth }));
vi.mock("@/hooks/use-desktop", () => ({
  useDesktopState: () => ({ data: env.state }),
  useSetBlobby: () => ({ mutate: env.setBlobby }),
  useSetWindowPreferences: () => ({ mutate: env.setWindow }),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ replace: env.replace }) }));
vi.mock("@/lib/desktop/commands", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/commands")>()),
  finishOnboarding: env.finish,
  notify: env.notify,
}));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: env.report,
}));

beforeEach(() => {
  env.shell = MAC_MAIN;
  env.auth = { isAuthenticated: true, isLoading: false };
  env.state = DESKTOP_STATE;
  vi.clearAllMocks();
});

const next = () => userEvent.click(screen.getByRole("button", { name: "Continue" }));

describe("DesktopWelcome", () => {
  it("walks through blobby, the shortcuts and notifications, then opens the console", async () => {
    render(<DesktopWelcome />);
    expect(screen.getByRole("heading", { name: "Meet blobby" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Sunny" }));
    expect(env.setBlobby).toHaveBeenCalledWith({
      ...DESKTOP_STATE.blobby,
      character: { kind: "cast", id: "sunny" },
      enabled: true,
    });

    await next();
    expect(screen.getByRole("heading", { name: "Two shortcuts, anywhere" })).toBeInTheDocument();
    expect(screen.getByText("⌥Space")).toBeInTheDocument();

    await next();
    await userEvent.click(screen.getByRole("switch", { name: "Open AgenticOS at login" }));
    expect(env.setWindow).toHaveBeenCalledWith({ ...DESKTOP_STATE.window, launch_at_login: true });
    await userEvent.click(
      screen.getByRole("switch", { name: "Keep running when the window is closed" }),
    );
    expect(env.setWindow).toHaveBeenLastCalledWith({
      ...DESKTOP_STATE.window,
      keep_running: false,
    });
    await userEvent.click(screen.getByRole("button", { name: "Send a test" }));
    expect(env.notify).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "inbox", path: "/dashboard" }),
    );
    expect(screen.getByRole("button", { name: "Sent" })).toBeDisabled();

    await next();
    expect(screen.getByRole("heading", { name: "You're all set" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip for now" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Open AgenticOS" }));
    expect(env.finish).toHaveBeenCalled();
    await vi.waitFor(() => expect(env.replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("can be skipped, and still marks itself as done", async () => {
    render(<DesktopWelcome />);
    await userEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    expect(env.finish).toHaveBeenCalled();
    await vi.waitFor(() => expect(env.replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("reports a shell that would not remember it, and still moves on", async () => {
    env.finish.mockRejectedValueOnce(new Error("refused"));
    env.notify.mockRejectedValueOnce(new Error("refused"));
    render(<DesktopWelcome />);
    await next();
    await next();
    await userEvent.click(screen.getByRole("button", { name: "Send a test" }));
    await userEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    await vi.waitFor(() => expect(env.replace).toHaveBeenCalledWith("/dashboard"));
    expect(env.report).toHaveBeenCalledWith("could not finish onboarding", expect.any(Error));
    expect(env.report).toHaveBeenCalledWith(
      "could not send a test notification",
      expect.any(Error),
    );
  });

  it("shows a shortcut that is off as off", async () => {
    env.state = {
      ...DESKTOP_STATE,
      shortcuts: [{ action: "quick_ask", accelerator: null, problem: null }],
    };
    env.shell = { ...MAC_MAIN, platform: "linux" };
    render(<DesktopWelcome />);
    await next();
    expect(screen.getByText("Off")).toBeInTheDocument();
  });

  it("goes through sign-in and back for somebody signed out, and waits while it does not know", () => {
    env.auth = { isAuthenticated: false, isLoading: true };
    const { container, rerender } = render(<DesktopWelcome />);
    expect(container).toBeEmptyDOMElement();
    expect(env.replace).not.toHaveBeenCalled();
    env.auth = { isAuthenticated: false, isLoading: false };
    act(() => rerender(<DesktopWelcome />));
    expect(env.replace).toHaveBeenCalledWith("/login?returnTo=%2Fdesktop%2Fwelcome");
  });

  it("says it belongs to the app in a browser", () => {
    env.shell = null;
    render(<DesktopWelcome />);
    expect(
      screen.getByText("This welcome belongs to the AgenticOS desktop app."),
    ).toBeInTheDocument();
  });
});
