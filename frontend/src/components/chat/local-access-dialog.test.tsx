import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { useConversationStore } from "@/stores";
import { useLocalAccessStore } from "@/stores/local-access-store";
import type { LocalTarget } from "@/lib/desktop/commands";

import { LocalAccessDialog } from "./local-access-dialog";

const desktop = vi.hoisted(() => ({
  allow: vi.fn(),
  pick: vi.fn(),
  linked: true,
  modes: ["workspace_write", "read_only", "full_access"],
}));
vi.mock("@/lib/desktop/commands", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/commands")>()),
  allowWholeComputer: desktop.allow,
}));
vi.mock("@/hooks/use-desktop", () => ({
  useDeviceStatus: () => ({ data: { linked: desktop.linked, connected: true } }),
  useDeviceLink: () => ({ link: { mutateAsync: vi.fn().mockResolvedValue({ linked: true }) } }),
  useLocalFolders: () => ({
    state: { data: { modes: desktop.modes } },
    pick: { mutateAsync: desktop.pick },
  }),
}));

function ask(coding = false): Promise<LocalTarget | null> {
  let answer!: Promise<LocalTarget | null>;
  act(() => {
    answer = useLocalAccessStore.getState().request({ id: "agent-1", name: "AgenticOS", coding });
  });
  return answer;
}

function mount() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <LocalAccessDialog />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  desktop.modes = ["workspace_write", "read_only", "full_access"];
  desktop.allow.mockReset();
  desktop.pick.mockReset();
  useConversationStore.setState({ currentConversationId: "chat" });
  useLocalAccessStore.setState({ asking: null, resolve: null });
});

it("asks for the whole computer for the agent by name", async () => {
  const whole = { folder: "/Users/person", mode: "full_access", computer_grant: "consent" };
  desktop.allow.mockResolvedValue(whole);
  mount();
  const answer = ask();
  expect(await screen.findByRole("dialog", { name: "Where may AgenticOS work?" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: /Whole computer/ }));
  await expect(answer).resolves.toEqual(whole);
  expect(desktop.allow).toHaveBeenCalledWith("chat", { id: "agent-1", name: "AgenticOS" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("picks a folder with full access for a coding agent", async () => {
  desktop.pick.mockResolvedValue({ path: "/work/app", mode: "full_access" });
  mount();
  const answer = ask(true);
  await userEvent.click(await screen.findByRole("button", { name: /Choose a folder/ }));
  await expect(answer).resolves.toEqual({ folder: "/work/app", mode: "full_access" });
  expect(desktop.pick).toHaveBeenCalledWith("full_access");
});

it("picks a writable folder for an agent with no coding agent", async () => {
  desktop.pick.mockResolvedValue({ path: "/work", mode: "workspace_write" });
  mount();
  const answer = ask();
  await userEvent.click(await screen.findByRole("button", { name: /Choose a folder/ }));
  await expect(answer).resolves.toEqual({ folder: "/work", mode: "workspace_write" });
  expect(desktop.pick).toHaveBeenCalledWith("workspace_write");
});

it("stays open when the native question is cancelled, and declines on Not now", async () => {
  desktop.allow.mockResolvedValue(null);
  mount();
  const answer = ask();
  await userEvent.click(await screen.findByRole("button", { name: /Whole computer/ }));
  await waitFor(() => expect(desktop.allow).toHaveBeenCalledOnce());
  expect(screen.getByRole("dialog")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Not now" }));
  await expect(answer).resolves.toBeNull();
});

it("uses a supported read-only mode on devices without workspace isolation", async () => {
  desktop.modes = ["read_only", "full_access"];
  desktop.pick.mockResolvedValue({ path: "/work", mode: "read_only" });
  mount();
  const answer = ask();
  await userEvent.click(await screen.findByRole("button", { name: /Choose a folder/ }));
  await expect(answer).resolves.toEqual({ folder: "/work", mode: "read_only" });
  expect(desktop.pick).toHaveBeenCalledWith("read_only");
});

it("shows the requesting turn's reason before granting remembered access", async () => {
  mount();
  act(() => {
    void useLocalAccessStore.getState().request({
      id: "agent-1",
      name: "AgenticOS",
      coding: false,
      reason: "Read the project README to explain its setup.",
    });
  });
  expect(await screen.findByText("Read the project README to explain its setup.")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Not now" }));
});
