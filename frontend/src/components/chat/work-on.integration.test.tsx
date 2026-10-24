import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";

import { WorkOn } from "./work-on";
import { useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { DeviceStatus, LocalGrant } from "@/lib/desktop/commands";

const native = vi.hoisted(() => ({
  pick: vi.fn<() => Promise<LocalGrant | null>>(),
  link: vi.fn<() => Promise<DeviceStatus>>(),
  linked: true,
}));
vi.mock("@/hooks/use-shell", () => ({
  useShell: () => ({ platform: "macos", window: "main", version: "0.2.0", vibrancy: false }),
}));
vi.mock("@/lib/desktop/commands", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/desktop/commands")>()),
  pickLocalFolder: native.pick,
  getLocalState: async () => ({ grants: [], modes: ["read_only", "full_access"] }),
}));
vi.mock("@/hooks/use-desktop", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-desktop")>()),
  useDeviceStatus: () => ({ data: { linked: native.linked, connected: native.linked } }),
  useDeviceLink: () => ({ link: { isPending: false, mutateAsync: native.link } }),
  useLocalServices: () => ({ state: { data: [] } }),
}));

beforeEach(() => {
  native.pick.mockReset();
  native.link.mockReset();
  native.linked = true;
  useConversationStore.setState({ currentConversationId: "chat" });
  useWorkOnStore.setState({ byConversation: {}, draft: null });
});

it("keeps the native folder choice when the settings close while the dialog is open", async () => {
  let finish: (grant: LocalGrant | null) => void = () => {
    throw new Error("Picker not opened");
  };
  native.pick.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <WorkOn />
    </QueryClientProvider>,
  );
  const computer = screen.getByRole("radio", { name: "This computer" });
  await waitFor(() => expect(computer).toBeEnabled());
  await userEvent.click(computer);
  await waitFor(() => expect(native.pick).toHaveBeenCalledOnce());
  view.unmount();
  useConversationStore.setState({ currentConversationId: "other" });
  await act(async () => finish({ path: "/approved/Desktop", mode: "read_only" }));
  await waitFor(() =>
    expect(useWorkOnStore.getState().targetFor("chat")).toEqual({
      folder: "/approved/Desktop",
      mode: "read_only",
    }),
  );
  expect(useWorkOnStore.getState().targetFor("other")).toBeNull();
  client.clear();
});

it("finishes pairing and picks for the original draft even after the popover closes", async () => {
  native.linked = false;
  useConversationStore.setState({ currentConversationId: null });
  let finish: (status: DeviceStatus) => void = () => {
    throw new Error("Pairing not opened");
  };
  native.link.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  native.pick.mockResolvedValue({ path: "/approved/Desktop", mode: "read_only" });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <WorkOn />
    </QueryClientProvider>,
  );
  const computer = screen.getByRole("radio", { name: "This computer" });
  await waitFor(() => expect(computer).toBeEnabled());
  await userEvent.click(computer);
  await waitFor(() => expect(native.link).toHaveBeenCalledOnce());
  view.unmount();
  await act(async () => finish({ linked: true, connected: true }));
  await waitFor(() =>
    expect(useWorkOnStore.getState().targetFor(null)).toEqual({
      folder: "/approved/Desktop",
      mode: "read_only",
    }),
  );
  useWorkOnStore.getState().adopt("created");
  expect(useWorkOnStore.getState().targetFor("created")).toEqual({
    folder: "/approved/Desktop",
    mode: "read_only",
  });
  expect(useWorkOnStore.getState().targetFor(null)).toBeNull();
  client.clear();
});
