import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { LocalAgentSettings } from "./local-agent-settings";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  invokeShell: invoke,
}));

const claude = {
  id: "claude_code",
  name: "Claude Code",
  installed: true,
  path: "/Users/me/.local/bin/claude",
  version: "2.1.316 (Claude Code)",
  signed_in: true,
};
const codex = {
  id: "codex",
  name: "Codex",
  installed: false,
  path: null,
  version: null,
  signed_in: null,
};

beforeEach(() => {
  window.__AGENTICOS_SHELL__ = {
    platform: "macos",
    version: "0.2.0",
    window: "main",
    vibrancy: true,
  };
  invoke.mockReset();
});
afterEach(() => {
  delete window.__AGENTICOS_SHELL__;
});
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
      }
    >
      <LocalAgentSettings />
    </QueryClientProvider>,
  );
}

it("shows each agent's state and offers only what applies", async () => {
  invoke.mockResolvedValueOnce([claude, codex]);
  mount();
  expect(await screen.findByText("2.1.316 (Claude Code)")).toBeInTheDocument();
  expect(screen.getByText("Signed in")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Sign out of Claude Code" })).toBeInTheDocument();
  expect(screen.getByText("Not installed")).toBeInTheDocument();
  expect(
    screen.getByText("AgenticOS can prepare Codex for you. No developer tools are needed."),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Sign in to Codex" })).toBeNull();
});

it("opens the agent's own sign-in, naming it by id and sending no credential", async () => {
  invoke.mockResolvedValueOnce([{ ...claude, signed_in: false }, codex]);
  invoke.mockResolvedValueOnce(undefined);
  invoke.mockResolvedValue([claude, codex]);
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Sign in to Claude Code" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("local_agent_sign_in", { id: "claude_code" }),
  );
});

it("replaces the agent with the state its own sign-out reports", async () => {
  invoke.mockResolvedValueOnce([claude, codex]);
  invoke.mockResolvedValueOnce({ ...claude, signed_in: false });
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Sign out of Claude Code" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("local_agent_sign_out", { id: "claude_code" }),
  );
  expect(await screen.findByRole("button", { name: "Sign in to Claude Code" })).toBeInTheDocument();
});

it("refuses an answer that names an unknown agent", async () => {
  invoke.mockResolvedValueOnce([{ ...claude, id: "other" }]);
  mount();
  expect(await screen.findByRole("alert")).toBeInTheDocument();
});

it("says when it cannot tell whether an installed agent is signed in", async () => {
  invoke.mockResolvedValueOnce([{ ...claude, signed_in: null }, codex]);
  mount();
  expect(await screen.findByText("Status unknown")).toBeInTheDocument();
});

it("prepares a missing agent through the app and refreshes its status", async () => {
  invoke.mockImplementation(async (command) =>
    command === "local_agent_prepare"
      ? { ...codex, installed: true, version: "0.165.0" }
      : [claude, codex],
  );
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Set up Codex" }));
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("local_agent_prepare", { id: "codex" }));
  await waitFor(() =>
    expect(
      invoke.mock.calls.filter(([command]) => command === "local_agents").length,
    ).toBeGreaterThan(1),
  );
});

it("reports preparation failures and permits retry", async () => {
  invoke.mockImplementation(async (command) => {
    if (command === "local_agent_prepare") throw new Error("Download unavailable");
    return [claude, codex];
  });
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Set up Codex" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Download unavailable");
  expect(screen.getByRole("button", { name: "Set up Codex" })).toBeEnabled();
});

it("does not probe credential storage again when the app regains focus", async () => {
  invoke.mockResolvedValue([claude, codex]);
  mount();
  await screen.findByText("Signed in");
  const before = invoke.mock.calls.length;
  await act(async () => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
    await Promise.resolve();
  });
  expect(invoke.mock.calls).toHaveLength(before);
  focusManager.setFocused(undefined);
  await userEvent.click(screen.getByRole("button", { name: "Refresh status" }));
  await waitFor(() => expect(invoke.mock.calls.length).toBeGreaterThan(before));
});
