import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { DeviceStatus } from "@/lib/desktop/commands";
import { WorkOn } from "./work-on";

const pick = vi.hoisted(() => vi.fn());
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
  useDeviceLink: () => ({ link: { mutate: link, isPending: deviceState.pending } }),
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
    pick: { mutate: pick, isPending: false },
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
  });
});
it("keeps local service choices when the approved folder changes", async () => {
  render(<WorkOn />);
  await userEvent.click(screen.getByRole("radio", { name: /second/ }));
  expect(useWorkOnStore.getState().targetFor("chat")).toEqual({
    folder: "/second",
    mode: "read_only",
    model_service: "model",
    mcp_services: ["files"],
    browser: true,
  });
});
it("applies local service choices to this conversation only", async () => {
  const user = userEvent.setup();
  render(<WorkOn />);
  await user.selectOptions(screen.getByRole("combobox"), "");
  for (const checkbox of screen.getAllByRole("checkbox")) await user.click(checkbox);
  expect(useWorkOnStore.getState().targetFor("chat")).toEqual({
    folder: "/first",
    mode: "read_only",
    model_service: null,
    mcp_services: [],
    browser: false,
  });
  expect(useWorkOnStore.getState().targetFor("other")).toBeNull();
});

it("selects an offered mode when this computer cannot sandbox shell commands", async () => {
  render(<WorkOn />);
  expect(screen.getByRole("button", { name: "Read only" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByRole("button", { name: /Choose a folder/ }));
  expect(pick).toHaveBeenCalledWith("read_only", expect.any(Object));
  await userEvent.click(screen.getByRole("button", { name: "Full access" }));
  await userEvent.click(screen.getByRole("button", { name: /Choose a folder/ }));
  expect(pick).toHaveBeenLastCalledWith("full_access", expect.any(Object));
});

it("waits for native access modes before granting another folder", async () => {
  modeState.ready = false;
  render(<WorkOn />);
  const choose = screen.getByRole("button", { name: /Choose a folder/ });
  expect(choose).toBeDisabled();
  await userEvent.click(choose);
  expect(pick).not.toHaveBeenCalled();
});

it("links from This computer and offers folders only after native confirmation", async () => {
  deviceState.linked = false;
  useWorkOnStore.getState().set("chat", null);
  const view = render(<WorkOn />);
  expect(link).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("radio", { name: "This computer" }));
  expect(link).toHaveBeenCalledOnce();
  expect(screen.getByRole("radio", { name: "Cloud" })).toHaveAttribute("aria-checked", "true");
  expect(screen.queryByRole("button", { name: /Choose a folder/ })).not.toBeInTheDocument();

  deviceState.linked = true;
  link.mock.calls[0]?.[1].onSuccess({ linked: true, connected: false });
  view.rerender(<WorkOn />);
  expect(screen.getByRole("radio", { name: "This computer" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(screen.getByRole("button", { name: /Choose a folder/ })).toBeEnabled();
  expect(useWorkOnStore.getState().targetFor("chat")).toBeNull();
  expect(pick).not.toHaveBeenCalled();
});

it("keeps Cloud selected when linking is refused or fails", async () => {
  deviceState.linked = false;
  useWorkOnStore.getState().set("chat", null);
  render(<WorkOn />);
  await userEvent.click(screen.getByRole("radio", { name: "This computer" }));
  link.mock.calls[0]?.[1].onSuccess({ linked: false, connected: false });
  expect(screen.getByRole("radio", { name: "Cloud" })).toHaveAttribute("aria-checked", "true");
  expect(useWorkOnStore.getState().targetFor("chat")).toBeNull();
  expect(pick).not.toHaveBeenCalled();
});

it("prevents another link while waiting for confirmation", async () => {
  deviceState.linked = false;
  deviceState.pending = true;
  useWorkOnStore.getState().set("chat", null);
  render(<WorkOn />);
  const computer = screen.getByRole("radio", { name: "Linking…" });
  expect(computer).toBeDisabled();
  expect(computer).toHaveAttribute("aria-busy", "true");
  expect(screen.getByRole("radio", { name: "Cloud" })).toBeDisabled();
  await userEvent.click(computer);
  expect(link).not.toHaveBeenCalled();
});

it("does not pair until the native device status has loaded", async () => {
  deviceState.ready = false;
  render(<WorkOn />);
  const computer = screen.getByRole("radio", { name: "This computer" });
  expect(computer).toBeDisabled();
  await userEvent.click(computer);
  expect(link).not.toHaveBeenCalled();
});

it("selects an already linked computer without pairing again", async () => {
  useWorkOnStore.getState().set("chat", null);
  render(<WorkOn />);
  await userEvent.click(screen.getByRole("radio", { name: "This computer" }));
  expect(screen.getByRole("button", { name: /Choose a folder/ })).toBeEnabled();
  expect(link).not.toHaveBeenCalled();
});

it("does not switch another conversation to the computer when pairing finishes", async () => {
  deviceState.linked = false;
  useWorkOnStore.getState().set("chat", null);
  const view = render(<WorkOn />);
  await userEvent.click(screen.getByRole("radio", { name: "This computer" }));
  useConversationStore.setState({ currentConversationId: "other" });
  deviceState.linked = true;
  link.mock.calls[0]?.[1].onSuccess({ linked: true, connected: false });
  view.rerender(<WorkOn />);
  expect(screen.getByRole("radio", { name: "Cloud" })).toHaveAttribute("aria-checked", "true");
  expect(useWorkOnStore.getState().targetFor("other")).toBeNull();
});
