import { useChatControlsStore } from "@/stores/chat-controls-store";
import { act, render as renderView, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement, ReactNode } from "react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { DeviceStatus, LocalGrant, LocalMode } from "@/lib/desktop/commands";
import { WorkOn } from "./work-on";

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderView(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

const pick = vi.hoisted(() =>
  vi.fn<(mode: LocalMode, options: { onSuccess: (grant: LocalGrant | null) => void }) => void>(),
);
const computer = vi.hoisted(() => ({ allow: vi.fn(), revoke: vi.fn() }));
vi.mock("./local-skills-control", () => ({
  LocalSkillsControl: () => <div data-testid="skills" />,
}));
vi.mock("@/lib/desktop/commands", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/commands")>()),
  allowWholeComputer: computer.allow,
  revokeWholeComputer: computer.revoke,
}));
const modeState = vi.hoisted(() => ({ ready: true }));
const deviceState = vi.hoisted(() => ({
  linked: true,
  connected: true,
  pending: false,
  ready: true,
}));
const link = vi.hoisted(() =>
  vi.fn<(value: undefined, options: { onSuccess: (status: DeviceStatus) => void }) => void>(),
);

vi.mock("@/hooks/use-shell", () => ({
  useShell: () => ({ platform: "macos", window: "main", version: "0.2.0", vibrancy: false }),
}));
vi.mock("@/hooks/use-desktop", () => ({
  useDeviceStatus: () => ({
    data: deviceState.ready
      ? { linked: deviceState.linked, connected: deviceState.connected }
      : undefined,
  }),
  useDeviceLink: () => ({
    link: {
      mutate: link,
      mutateAsync: () =>
        new Promise<DeviceStatus>((resolve) => link(undefined, { onSuccess: resolve })),
      isPending: deviceState.pending,
    },
  }),
  useLocalFolders: () => ({
    state: {
      data: {
        grants: [
          { path: "/first", mode: "read_only" },
          { path: "/second", mode: "read_only" },
        ],
        modes: modeState.ready ? ["read_only", "full_access"] : [],
      },
    },
    pick: {
      mutate: pick,
      mutateAsync: (mode: LocalMode) =>
        new Promise<LocalGrant | null>((resolve) => pick(mode, { onSuccess: resolve })),
      isPending: false,
    },
    revoke: { mutate: vi.fn() },
  }),
  useLocalServices: () => ({
    state: {
      data: [
        { id: "model", name: "Local model", kind: "model", model: "installed" },
        { id: "files", name: "Local files", kind: "mcp", model: null },
      ],
    },
  }),
}));
beforeEach(() => {
  useChatControlsStore.setState({ byScope: {} });
  computer.allow.mockReset();
  computer.revoke.mockReset();
  pick.mockClear();
  link.mockReset();
  Object.assign(deviceState, { linked: true, connected: true, pending: false, ready: true });
  modeState.ready = true;
  useConversationStore.setState({ currentConversationId: "chat" });
  useWorkOnStore.setState({
    byConversation: {
      chat: {
        folder: "/first",
        mode: "read_only",
        model_service: "model",
        mcp_services: ["files"],
        browser: true,
      },
    },
    draft: null,
    computerByConversation: {},
    draftComputer: undefined,
  });
});
it("keeps local service choices when the approved folder changes", async () => {
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  await userEvent.click(screen.getByRole("radio", { name: /second/ }));
  expect(useWorkOnStore.getState().targetFor("chat")).toEqual({
    folder: "/second",
    mode: "read_only",
    model_service: "model",
    mcp_services: ["files"],
    browser: true,
  });
});
it("remembers local service choices for subsequent conversations", async () => {
  const user = userEvent.setup();
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  await user.selectOptions(screen.getByRole("combobox", { name: "Model for this chat" }), "");
  for (const checkbox of screen.getAllByRole("checkbox")) await user.click(checkbox);
  expect(useWorkOnStore.getState().targetFor("chat")).toEqual({
    folder: "/first",
    mode: "read_only",
    model_service: null,
    mcp_services: [],
    browser: true,
  });
  expect(useWorkOnStore.getState().targetFor("other")).toEqual(
    useWorkOnStore.getState().targetFor("chat"),
  );
});

it("selects an offered mode when this computer cannot sandbox shell commands", async () => {
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  const access = screen.getByRole("combobox", { name: "Folder access" });
  expect(access).toHaveValue("read_only");
  expect(access).toHaveAccessibleDescription(
    "Agents read files here; nothing is written and no command runs.",
  );
  await userEvent.click(screen.getByRole("button", { name: /Choose a folder/ }));
  expect(pick).toHaveBeenCalledWith("read_only", expect.any(Object));
  await userEvent.selectOptions(access, "full_access");
  expect(pick).toHaveBeenLastCalledWith("full_access", expect.any(Object));
  expect(useWorkOnStore.getState().targetFor("chat")?.mode).toBe("read_only");
  await act(async () =>
    pick.mock.calls.at(-1)?.[1].onSuccess({ path: "/first", mode: "full_access" }),
  );
  expect(access).toHaveValue("full_access");
  expect(access).toHaveAccessibleDescription("Commands run as you, and each one asks you first.");
  expect(useWorkOnStore.getState().targetFor("chat")?.mode).toBe("full_access");
});

it("waits for native access modes before granting another folder", async () => {
  modeState.ready = false;
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  const choose = screen.getByRole("button", { name: /Choose a folder/ });
  expect(choose).toBeDisabled();
  await userEvent.click(choose);
  expect(pick).not.toHaveBeenCalled();
});

it("links from This computer and offers folders only after native confirmation", async () => {
  deviceState.linked = false;
  useWorkOnStore.getState().set("chat", null);
  const view = render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  expect(link).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("radio", { name: "This computer" }));
  expect(link).toHaveBeenCalledOnce();
  expect(screen.getByRole("radio", { name: "Cloud" })).toHaveAttribute("aria-checked", "true");
  expect(screen.queryByRole("button", { name: /Choose a folder/ })).not.toBeInTheDocument();

  deviceState.linked = true;
  await act(async () => link.mock.calls[0]?.[1].onSuccess({ linked: true, connected: false }));
  view.rerender(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  expect(pick).toHaveBeenCalledWith("read_only", expect.any(Object));
  expect(screen.getByRole("radio", { name: "Cloud" })).toHaveAttribute("aria-checked", "true");
  expect(useWorkOnStore.getState().targetFor("chat")).toBeNull();
  await act(async () =>
    pick.mock.calls.at(-1)?.[1].onSuccess({ path: "/first", mode: "read_only" }),
  );
  expect(screen.getByRole("radio", { name: "This computer" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(screen.getByRole("button", { name: /Choose a folder/ })).toBeEnabled();
});

it("keeps Cloud selected when linking is refused or fails", async () => {
  deviceState.linked = false;
  useWorkOnStore.getState().set("chat", null);
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  await userEvent.click(screen.getByRole("radio", { name: "This computer" }));
  await act(async () => link.mock.calls[0]?.[1].onSuccess({ linked: false, connected: false }));
  expect(screen.getByRole("radio", { name: "Cloud" })).toHaveAttribute("aria-checked", "true");
  expect(useWorkOnStore.getState().targetFor("chat")).toBeNull();
  expect(pick).not.toHaveBeenCalled();
});

it("prevents another link while waiting for confirmation", async () => {
  deviceState.linked = false;
  deviceState.pending = true;
  useWorkOnStore.getState().set("chat", null);
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  const computer = screen.getByRole("radio", { name: "Linking…" });
  expect(computer).toBeDisabled();
  expect(computer).toHaveAttribute("aria-busy", "true");
  expect(screen.getByRole("radio", { name: "Cloud" })).toBeDisabled();
  await userEvent.click(computer);
  expect(link).not.toHaveBeenCalled();
});

it("does not pair until the native device status has loaded", async () => {
  deviceState.ready = false;
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  const computer = screen.getByRole("radio", { name: "This computer" });
  expect(computer).toBeDisabled();
  await userEvent.click(computer);
  expect(link).not.toHaveBeenCalled();
});

it("selects an already linked computer without pairing again", async () => {
  useWorkOnStore.getState().set("chat", null);
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  await userEvent.click(screen.getByRole("radio", { name: "This computer" }));
  expect(pick).toHaveBeenCalledWith("read_only", expect.any(Object));
  expect(screen.getByRole("radio", { name: "Cloud" })).toHaveAttribute("aria-checked", "true");
  await act(async () =>
    pick.mock.calls.at(-1)?.[1].onSuccess({ path: "/first", mode: "read_only" }),
  );
  expect(screen.getByRole("radio", { name: "This computer" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(link).not.toHaveBeenCalled();
});

it("does not switch another conversation to the computer when pairing finishes", async () => {
  deviceState.linked = false;
  useWorkOnStore.getState().set("chat", null);
  const view = render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  await userEvent.click(screen.getByRole("radio", { name: "This computer" }));
  act(() => useConversationStore.setState({ currentConversationId: "other" }));
  deviceState.linked = true;
  await act(async () => link.mock.calls[0]?.[1].onSuccess({ linked: true, connected: false }));
  view.rerender(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  expect(screen.getByRole("radio", { name: "Cloud" })).toHaveAttribute("aria-checked", "true");
  expect(useWorkOnStore.getState().targetFor("other")).toEqual(
    useWorkOnStore.getState().targetFor("chat"),
  );
});

it("keeps the approved folder and mode when the settings popover remounts", () => {
  useWorkOnStore.getState().set("chat", { folder: "/first", mode: "full_access" });
  const view = render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  view.unmount();
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  expect(screen.getByRole("radio", { name: "This computer" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(screen.getByRole("combobox", { name: "Folder access" })).toHaveValue("full_access");
});

it("keeps the actual grant when a requested access change is cancelled", async () => {
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  await userEvent.selectOptions(
    screen.getByRole("combobox", { name: "Folder access" }),
    "full_access",
  );
  await act(async () => pick.mock.calls.at(-1)?.[1].onSuccess(null));
  expect(screen.getByRole("combobox", { name: "Folder access" })).toHaveValue("read_only");
  expect(useWorkOnStore.getState().targetFor("chat")?.mode).toBe("read_only");
});

it("does not show a local selection if the folder picker is cancelled", async () => {
  useWorkOnStore.getState().set("chat", null);
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  await userEvent.click(screen.getByRole("radio", { name: "This computer" }));
  await act(async () => pick.mock.calls.at(-1)?.[1].onSuccess(null));
  expect(screen.getByRole("radio", { name: "Cloud" })).toHaveAttribute("aria-checked", "true");
  expect(useWorkOnStore.getState().targetFor("chat")).toBeNull();
});

it("selects a local browser while keeping the cloud sandbox and never asks for a folder", async () => {
  useWorkOnStore.setState({
    byConversation: {},
    browserByConversation: {},
    draftBrowser: undefined,
  });
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  await userEvent.click(screen.getByRole("radio", { name: "Local browser" }));
  expect(useWorkOnStore.getState().browserFor("chat")).toBe(true);
  expect(useWorkOnStore.getState().targetFor("chat")).toBeNull();
  expect(pick).not.toHaveBeenCalled();
  await userEvent.click(
    within(screen.getByRole("radiogroup", { name: "Browser" })).getByRole("radio", {
      name: "Agent setting",
    }),
  );
  expect(useWorkOnStore.getState().browserFor("chat")).toBe(false);
});

it("requires native consent for whole-computer access without picking a folder and revokes it", async () => {
  const user = userEvent.setup();
  const grant = { folder: "/Users/person", mode: "full_access", computer_grant: "native-consent" };
  computer.allow.mockResolvedValueOnce(null).mockResolvedValueOnce(grant);
  computer.revoke.mockResolvedValue(undefined);
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  const before = useWorkOnStore.getState().targetFor("chat");
  await user.click(screen.getByRole("button", { name: "Whole computer" }));
  expect(computer.allow).toHaveBeenCalledWith("chat");
  expect(useWorkOnStore.getState().targetFor("chat")).toEqual(before);
  await user.click(screen.getByRole("button", { name: "Whole computer" }));
  expect(
    await screen.findByRole("button", { name: "Revoke whole-computer access" }),
  ).toBeInTheDocument();
  expect(useWorkOnStore.getState().targetFor("chat")).toMatchObject(grant);
  expect(pick).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Revoke whole-computer access" }));
  expect(computer.revoke).toHaveBeenCalledWith("native-consent");
  expect(useWorkOnStore.getState().targetFor("chat")).toBeNull();
});

it("keeps whole-computer access visible when revocation fails", async () => {
  const user = userEvent.setup();
  useWorkOnStore
    .getState()
    .set("chat", { folder: "/Users/person", mode: "full_access", computer_grant: "saved" });
  computer.revoke.mockRejectedValue(new Error("Could not save"));
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  await user.click(screen.getByRole("radio", { name: "Cloud" }));
  expect(
    await screen.findByRole("button", { name: "Revoke whole-computer access" }),
  ).toBeInTheDocument();
  expect(useWorkOnStore.getState().targetFor("chat")?.computer_grant).toBe("saved");
});

it("keeps browser and workspace explanations behind their header information buttons", async () => {
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  const browserHint = /Available in desktop chat even when the agent has no browser capability/;
  const workspaceHint = /Local tools are available here without enabling Sandbox/;
  expect(screen.queryByText(browserHint)).not.toBeInTheDocument();
  expect(screen.queryByText(workspaceHint)).not.toBeInTheDocument();
  const help = screen.getAllByRole("button", { name: "More information" });
  await userEvent.click(help[0]!);
  expect(screen.getByText(browserHint)).toBeVisible();
  await userEvent.keyboard("{Escape}");
  await userEvent.click(help[2]!);
  expect(screen.getByText(workspaceHint)).toBeVisible();
});

it("opts into local computer use without granting files or changing the browser", async () => {
  useWorkOnStore.getState().resetDraft();
  useConversationStore.setState({ currentConversationId: null });
  render(<WorkOn agentCapabilities={["sandbox", "browser_use", "computer_use"]} />);
  const group = screen.getByRole("radiogroup", { name: "Computer use" });
  await userEvent.click(within(group).getByRole("radio", { name: "Local computer" }));
  expect(useWorkOnStore.getState().computerFor(null)).toBe(true);
  expect(useWorkOnStore.getState().browserFor(null)).toBe(false);
  expect(useWorkOnStore.getState().targetFor(null)).toBeNull();
  expect(pick).not.toHaveBeenCalled();
  expect(computer.allow).not.toHaveBeenCalled();
  await userEvent.click(within(group).getByRole("radio", { name: "Agent setting" }));
  expect(useWorkOnStore.getState().computerFor(null)).toBe(false);
});

it("disables absent agent capabilities without choosing local access", () => {
  useWorkOnStore.setState({
    byConversation: {},
    draft: null,
    browserByConversation: {},
    computerByConversation: {},
  });
  useChatControlsStore.setState({ byScope: {} });
  render(<WorkOn agentCapabilities={[]} />);
  for (const option of screen.getAllByRole("radio", { name: "Agent setting" })) {
    expect(option).toBeDisabled();
    expect(option).toHaveAttribute("aria-checked", "false");
  }
  expect(screen.getByRole("radio", { name: "Cloud" })).toBeDisabled();
  expect(screen.getByRole("radio", { name: "Local browser" })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  expect(screen.getByRole("radio", { name: "Local computer" })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  expect(pick).not.toHaveBeenCalled();
  expect(computer.allow).not.toHaveBeenCalled();
});

it("can turn off local use even when the agent has no equivalent capability", async () => {
  useWorkOnStore.getState().setComputer("chat", true);
  render(<WorkOn agentCapabilities={[]} />);
  const group = screen.getByRole("radiogroup", { name: "Computer use" });
  await userEvent.click(within(group).getByRole("radio", { name: "Local computer" }));
  expect(useWorkOnStore.getState().computerFor("chat")).toBe(false);
});
